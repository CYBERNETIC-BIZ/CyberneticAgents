"""Generate a persona agent from a CyberneticAgents research report."""
import json
import re
from datetime import datetime
from typing import Dict, Any, Optional, List
from cybernetic.storage.db import save_agent
from cybernetic.storage.models import Agent
from cybernetic.agents.names import generate_funny_name
from cybernetic.llm import create_llm_client

ALLOWED_TARGET_DAYS = [1, 3, 5, 7, 14, 30]


def pick_target_days_from_report(report_text: str, decision: str, ticker: str, config: dict) -> int:
    """Use the LLM to pick the best target_days from a research report.

    Args:
        report_text: The full research report text
        decision: BUY/SELL/HOLD decision
        ticker: The researched ticker
        config: App config with llm_provider, quick_think_llm, etc.

    Returns:
        One of ALLOWED_TARGET_DAYS
    """
    client = create_llm_client(
        provider=config["llm_provider"],
        model=config["quick_think_llm"],
    )
    llm = client.get_llm()

    system = f"""\
You are a trading timeframe analyst. Given a research report and trading decision for {ticker}, \
pick the most appropriate prediction target in days.

Allowed values: {ALLOWED_TARGET_DAYS}

Consider:
- Short-term catalysts (earnings, events) → 1-3 days
- Technical momentum plays → 3-7 days
- Fundamental / value plays → 7-14 days
- Macro / long-term thesis → 14-30 days
- HOLD decisions with uncertainty → shorter timeframes (3-5 days)

Respond with ONLY a JSON object: {{"target_days": <number>}}"""

    messages = [
        ("system", system),
        ("human", f"Decision: {decision}\n\nReport:\n{report_text[:4000]}"),
    ]
    response = llm.invoke(messages)
    content = response.content

    json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            td = int(data.get("target_days", 7))
            return min(ALLOWED_TARGET_DAYS, key=lambda x: abs(x - td))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return 7


def generate_agent_from_report(
    final_state: Dict[str, Any],
    decision: str,
    ticker: str,
    agent_name: Optional[str] = None,
    description: str = "",
    tools: Optional[List[str]] = None,
    target_days: int = 7,
    max_positions: int = 1,
    personality: str = "",
    analysis_temperature: Optional[float] = None,
    comment_system_prompt: str = "",
    comment_temperature: float = 0.8,
) -> Agent:
    """Generate a persona agent config from a completed research report.

    Args:
        final_state: The final state dict from CyberneticAgentsGraph
        decision: The extracted BUY/SELL/HOLD decision
        ticker: The researched ticker
        agent_name: Optional custom name. Auto-generated with funny name if None.
        description: Agent description text
        tools: List of analyst types used (e.g. ["market", "news"])
        target_days: Default prediction target in days
        max_positions: Max concurrent positions
        personality: Personality trait description
        analysis_temperature: Override temp (auto-determined from decision if None)
        comment_system_prompt: System prompt for commentary generation
        comment_temperature: Temperature for commentary

    Returns:
        Saved Agent instance
    """
    if not agent_name:
        agent_name = generate_funny_name()

    # Build the research report text
    report_parts = []
    if final_state.get("market_report"):
        report_parts.append(f"## Market Analysis\n{final_state['market_report']}")
    if final_state.get("sentiment_report"):
        report_parts.append(f"## Sentiment Analysis\n{final_state['sentiment_report']}")
    if final_state.get("news_report"):
        report_parts.append(f"## News Analysis\n{final_state['news_report']}")
    if final_state.get("fundamentals_report"):
        report_parts.append(f"## Fundamentals Analysis\n{final_state['fundamentals_report']}")
    if final_state.get("investment_plan"):
        report_parts.append(f"## Investment Plan\n{final_state['investment_plan']}")
    if final_state.get("trader_investment_plan"):
        report_parts.append(f"## Trader Plan\n{final_state['trader_investment_plan']}")
    if final_state.get("final_trade_decision"):
        report_parts.append(f"## Final Decision\n{final_state['final_trade_decision']}")

    research_report = "\n\n".join(report_parts)

    # Determine temperature based on decision confidence (if not overridden)
    if analysis_temperature is None:
        analysis_temperature = 0.7
        if decision.upper() == "HOLD":
            analysis_temperature = 0.6
        elif decision.upper() == "SELL":
            analysis_temperature = 0.65

    # Build system prompt that bakes in the research
    direction_bias = {
        "BUY": "bullish",
        "SELL": "bearish",
        "HOLD": "bullish",
    }.get(decision.upper(), "bullish")

    system_prompt = f"""You are an autonomous trading agent for {ticker} with a {direction_bias} bias.

You were created based on the following comprehensive research analysis:

{research_report}

Your task: Given current market data, decide whether to go BULLISH or BEARISH on {ticker}.
Use your research knowledge to inform your decision. Consider how current conditions compare to your analysis.

Respond with a JSON object:
{{
    "direction": "BULLISH" or "BEARISH",
    "confidence": 0.5 to 0.95,
    "reasoning": "2-3 sentence explanation referencing your research",
    "target_days": 1 to 14
}}"""

    tools_list = tools or []

    persona_config = {
        "name": agent_name,
        "ticker": ticker,
        "direction_bias": direction_bias,
        "decision": decision.upper(),
        "analysis_system_prompt": system_prompt,
        "analysis_temperature": analysis_temperature,
        "created_from_research": True,
        "research_date": datetime.now().strftime("%Y-%m-%d"),
    }

    agent = Agent(
        id=agent_name,
        name=agent_name,
        ticker=ticker,
        persona_json=json.dumps(persona_config),
        research_report=research_report,
        description=description,
        tools=json.dumps(tools_list),
        analysis_system_prompt=system_prompt,
        comment_system_prompt=comment_system_prompt,
        analysis_temperature=analysis_temperature,
        comment_temperature=comment_temperature,
        target_days=target_days,
        max_positions=max_positions,
        personality=personality,
        direction_bias=direction_bias,
        created_from="research",
    )

    saved = save_agent(agent)

    # Register on cybernetic.biz immediately
    from cybernetic.agents.runner import register_agent_on_cybernetic
    register_agent_on_cybernetic(saved)

    return saved
