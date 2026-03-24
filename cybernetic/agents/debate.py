"""Lightweight 3-agent debate for predictions on 2nd+ runs.

Reuses the existing bull/bear/manager factory functions from the research pipeline.
"""

import re

from cybernetic.research.agents.researchers.bull_researcher import create_bull_researcher
from cybernetic.research.agents.researchers.bear_researcher import create_bear_researcher
from cybernetic.research.agents.managers.research_manager import create_research_manager
from cybernetic.research.agents.utils.memory import FinancialSituationMemory


def run_lightweight_debate(
    ticker: str,
    market_context: str,
    news_context: str,
    prediction_history: str,
    original_research: str,
    llm,
    rounds: int = 1,
    on_status=None,
) -> dict:
    """Run a Bull vs Bear vs Judge debate and return the result.

    Args:
        ticker: The asset ticker symbol
        market_context: Fresh 30-day yfinance market data string
        news_context: Recent news headlines + sentiment block (may be empty)
        prediction_history: Formatted past prediction results (may be empty)
        original_research: The agent's baked-in research_report (may be empty)
        llm: LangChain-compatible LLM instance
        rounds: Number of bull/bear exchange rounds before judge decides

    Returns:
        dict with keys: direction, confidence, reasoning, debate_history
    """
    # Build the 4 report fields the debate agents expect
    market_report = market_context
    if prediction_history:
        market_report += f"\n\nPast Prediction History:\n{prediction_history}"

    sentiment_report = news_context if news_context else _extract_section(original_research, "sentiment")
    news_report = news_context if news_context else _extract_section(original_research, "news")
    fundamentals_report = _extract_section(original_research, "fundamental")

    # Create fresh empty memories (no past debate memory for now)
    bull_memory = FinancialSituationMemory(name=f"{ticker}_bull_debate")
    bear_memory = FinancialSituationMemory(name=f"{ticker}_bear_debate")
    judge_memory = FinancialSituationMemory(name=f"{ticker}_judge_debate")

    # Build initial debate state
    state = {
        "market_report": market_report,
        "sentiment_report": sentiment_report,
        "news_report": news_report,
        "fundamentals_report": fundamentals_report,
        "investment_debate_state": {
            "history": "",
            "bull_history": "",
            "bear_history": "",
            "current_response": "",
            "count": 0,
        },
    }

    # Create debate agent nodes
    bull_node = create_bull_researcher(llm, bull_memory)
    bear_node = create_bear_researcher(llm, bear_memory)
    judge_node = create_research_manager(llm, judge_memory)

    # Run debate rounds: Bull → Bear for each round
    for rnd in range(rounds):
        if on_status:
            on_status(f"Bull researcher arguing for {ticker}...")
        bull_result = bull_node(state)
        state["investment_debate_state"] = bull_result["investment_debate_state"]

        if on_status:
            on_status(f"Bear researcher arguing against {ticker}...")
        bear_result = bear_node(state)
        state["investment_debate_state"] = bear_result["investment_debate_state"]

    # Judge makes the final call
    if on_status:
        on_status(f"Judge evaluating arguments for {ticker}...")
    judge_result = judge_node(state)
    state["investment_debate_state"] = judge_result["investment_debate_state"]
    judge_decision = judge_result.get("investment_plan", "")

    # Parse the judge's decision
    direction, confidence, reasoning = _parse_judge_decision(judge_decision)

    return {
        "direction": direction,
        "confidence": confidence,
        "reasoning": reasoning,
        "debate_history": state["investment_debate_state"].get("history", ""),
    }


def _extract_section(report: str, keyword: str) -> str:
    """Try to extract a section from a research report by keyword.

    Looks for headings containing the keyword and returns content until the next heading.
    Returns empty string if not found or report is empty.
    """
    if not report:
        return ""

    lines = report.split("\n")
    capturing = False
    section_lines = []

    for line in lines:
        stripped = line.strip().lower()
        # Check if this is a heading containing our keyword
        is_heading = stripped.startswith("#") or stripped.startswith("**")
        if is_heading and keyword.lower() in stripped:
            capturing = True
            section_lines.append(line)
            continue
        if capturing:
            # Stop at the next heading
            if is_heading and keyword.lower() not in stripped:
                break
            section_lines.append(line)

    return "\n".join(section_lines).strip() if section_lines else ""


def _parse_judge_decision(decision_text: str) -> tuple:
    """Parse judge's decision text into (direction, confidence, reasoning).

    Returns defaults if parsing fails: ("BULLISH", 0.5, raw_text)
    """
    if not decision_text:
        return ("BULLISH", 0.5, "No judge decision available")

    text_upper = decision_text.upper()

    # Determine direction from Buy/Sell/Hold keywords
    buy_signals = len(re.findall(r'\b(BUY|BULLISH|LONG)\b', text_upper))
    sell_signals = len(re.findall(r'\b(SELL|BEARISH|SHORT)\b', text_upper))
    hold_signals = len(re.findall(r'\bHOLD\b', text_upper))

    if sell_signals > buy_signals and sell_signals >= hold_signals:
        direction = "BEARISH"
    else:
        direction = "BULLISH"

    # Try to extract a confidence value (look for percentages or decimal values)
    conf_match = re.search(r'(?:confidence|probability|certainty)[:\s]*(\d+(?:\.\d+)?)\s*%?', decision_text, re.IGNORECASE)
    if conf_match:
        conf_val = float(conf_match.group(1))
        confidence = conf_val / 100.0 if conf_val > 1.0 else conf_val
        confidence = min(max(confidence, 0.5), 0.95)
    else:
        # Default confidence based on signal strength
        total_signals = buy_signals + sell_signals
        if total_signals > 0:
            dominant = max(buy_signals, sell_signals)
            confidence = min(0.5 + (dominant / total_signals) * 0.3, 0.85)
        else:
            confidence = 0.5

    # Use first 2-3 sentences as reasoning, fall back to truncated text
    sentences = re.split(r'(?<=[.!?])\s+', decision_text.strip())
    reasoning = " ".join(sentences[:3]) if sentences else decision_text[:500]
    if len(reasoning) > 500:
        reasoning = reasoning[:497] + "..."

    return (direction, confidence, reasoning)
