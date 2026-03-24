"""Run a generated agent for a single prediction."""
import json
import re
from datetime import datetime, timedelta
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from cybernetic.config import get_config
from cybernetic.storage.db import (
    get_agent, save_prediction, save_trade,
    update_agent_balance, get_agent_stats,
    get_recent_resolved_predictions,
    get_trade_for_prediction,
)
from cybernetic.storage.models import Agent, Prediction, Trade

console = Console()


def build_prediction_history_block(predictions: list) -> str:
    """Format resolved predictions as a context block for the LLM."""
    if not predictions:
        return ""

    lines = ["Past Prediction History:"]
    for p in predictions:
        result_str = (p.result or "UNKNOWN").upper()
        resolved_date = p.resolved_at.strftime("%Y-%m-%d") if p.resolved_at else "N/A"
        entry = p.entry_price
        exit_val = p.exit_price if p.exit_price else entry
        pnl = ((exit_val - entry) / entry * 100) if entry else 0
        if p.direction == "BEARISH":
            pnl = -pnl

        lines.append(
            f"  [{resolved_date}] {p.direction} @ {p.confidence:.0%} | "
            f"Entry: ${entry:.2f} -> Exit: ${exit_val:.2f} | "
            f"Result: {result_str} | P&L: {pnl:+.2f}%"
        )

    return "\n".join(lines)


def run_agent_once(agent_id: str, push_to_cybernetic: bool = True) -> Optional[Prediction]:
    """Run an agent for a single prediction cycle.

    Args:
        agent_id: The agent ID to run
        push_to_cybernetic: Whether to push prediction to cybernetic.biz

    Returns:
        The created Prediction, or None if failed
    """
    agent = get_agent(agent_id)
    if not agent:
        console.print(f"[red]Agent '{agent_id}' not found.[/red]")
        return None

    persona = json.loads(agent.persona_json)
    config = get_config()

    # Resolve system prompt: prefer direct field, fall back to persona_json
    system_prompt = agent.analysis_system_prompt or persona.get("analysis_system_prompt", "")
    analysis_temp = agent.analysis_temperature if agent.analysis_temperature != 0.7 else persona.get("analysis_temperature", 0.7)
    default_target_days = agent.target_days

    # Parse ticker list early so we know if multi-ticker
    tickers_list = [t.strip() for t in agent.ticker.split(",") if t.strip()]
    is_multi_ticker = len(tickers_list) > 1

    # Ensure the system prompt always includes the JSON response format
    ticker_field = ""
    if is_multi_ticker:
        ticker_field = f'    "ticker": "one of {", ".join(tickers_list)} — the ticker you are trading",\n'
    json_instruction = (
        '\n\nYou MUST respond with ONLY a JSON object, no other text:\n'
        '{\n'
        f'{ticker_field}'
        '    "direction": "BULLISH" or "BEARISH",\n'
        '    "confidence": 0.5 to 0.95,\n'
        '    "reasoning": "2-3 sentence explanation",\n'
        f'    "target_days": 1 to {max(default_target_days, 14)},\n'
        '    "position_size": 5 to 100 (percentage of available cash to allocate)\n'
        '}'
    )
    if '"direction"' not in system_prompt:
        system_prompt = system_prompt + json_instruction

    # Fetch current market data for all tickers
    import yfinance as yf
    ticker_market_data: dict[str, dict] = {}

    for _tk in tickers_list:
        try:
            with console.status(f"  [cyan]Fetching market data for {_tk}...[/cyan]", spinner="dots"):
                _td = yf.Ticker(_tk)
                _hist = _td.history(period="30d")
            console.print(f"  [cyan]Fetching market data for {_tk}...[/cyan] [green]done[/green]")
            if _hist.empty:
                console.print(f"[yellow]No market data for {_tk}, skipping.[/yellow]")
                continue
            _cp = _hist["Close"].iloc[-1]
            _pc = ((_cp - _hist["Close"].iloc[0]) / _hist["Close"].iloc[0]) * 100
            _block = (
                f"Current Market Data for {_tk}:\n"
                f"- Current Price: ${_cp:.2f}\n"
                f"- 30-Day Price Change: {_pc:+.2f}%\n"
                f"- 30-Day High: ${_hist['High'].max():.2f}\n"
                f"- 30-Day Low: ${_hist['Low'].min():.2f}\n"
                f"- Average Volume: {_hist['Volume'].mean():,.0f}\n"
                f"- Date: {datetime.now().strftime('%Y-%m-%d')}"
            )
            ticker_market_data[_tk] = {
                "hist": _hist,
                "current_price": _cp,
                "price_change_30d": _pc,
                "market_block": _block,
            }
        except Exception as e:
            console.print(f"  [cyan]Fetching market data for {_tk}...[/cyan] [red]failed[/red]")
            console.print(f"[yellow]Error fetching {_tk}: {e}[/yellow]")

    if not ticker_market_data:
        console.print(f"[red]No market data available for any ticker ({agent.ticker})[/red]")
        return None

    market_context = "\n\n".join(d["market_block"] for d in ticker_market_data.values())

    if not is_multi_ticker:
        _first_tk = next(iter(ticker_market_data))
        current_price = ticker_market_data[_first_tk]["current_price"]
    else:
        market_context += (
            "\n\nYou are monitoring multiple tickers. Pick the BEST ticker to trade right now. "
            'Include a "ticker" field in your JSON response with the chosen symbol.'
        )

    # Create LLM client (used for both single-call and debate paths)
    from cybernetic.llm import create_llm_client
    try:
        client = create_llm_client(
            provider=config["llm_provider"],
            model=config["quick_think_llm"],
        )
        llm = client.get_llm()
    except Exception as e:
        console.print(f"[red]Error creating LLM client: {e}[/red]")
        return None

    # Determine if this is a first run or 2nd+ run
    stats = get_agent_stats(agent.id)
    is_first_run = stats["total"] == 0

    # --- Tier logic for 2nd+ runs ---
    from cybernetic.agents.staleness import (
        RefreshTier, get_research_date, get_staleness_thresholds,
        compute_staleness_days, classify_tier,
    )
    history_block = ""
    news_context_block = ""
    tier = RefreshTier.QUICK

    if not is_first_run:
        # Classify staleness tier
        research_date = get_research_date(agent)
        staleness_days = compute_staleness_days(research_date)
        thresholds = get_staleness_thresholds(agent.tools)
        tier = classify_tier(staleness_days, thresholds)

        # All tiers: build prediction history
        resolved_preds = get_recent_resolved_predictions(agent.id, limit=5)
        history_block = build_prediction_history_block(resolved_preds)

        # Tier 2+: fetch news and sentiment
        if tier >= RefreshTier.LIGHTWEIGHT:
            from cybernetic.agents.news_context import (
                fetch_news_headlines, summarize_news_sentiment,
                build_news_context_block,
            )
            all_headlines = []
            for _tk in tickers_list:
                with console.status(f"  [cyan]Fetching recent news for {_tk}...[/cyan]", spinner="dots"):
                    _hdl = fetch_news_headlines(_tk)
                console.print(f"  [cyan]Fetching recent news for {_tk}...[/cyan] [green]done[/green]")
                all_headlines.extend(_hdl)
            headlines = all_headlines
            sentiment_summary = ""
            if headlines:
                with console.status(f"  [cyan]Summarizing news sentiment for {agent.ticker}...[/cyan]", spinner="dots"):
                    sentiment_summary = summarize_news_sentiment(headlines, agent.ticker, llm)
                console.print(f"  [cyan]Summarizing news sentiment for {agent.ticker}...[/cyan] [green]done[/green]")
            news_context_block = build_news_context_block(headlines, sentiment_summary)

        # Tier 3: show stale warning (falls through to Tier 2 behavior)
        if tier == RefreshTier.FULL_RESTALE:
            console.print(Panel(
                f"[yellow]Research is {staleness_days} days old. "
                f"Consider re-running full analysis for {agent.ticker}.[/yellow]",
                title="Stale Research Warning",
                border_style="yellow",
            ))

        # Display tier notification
        tier_names = {
            RefreshTier.QUICK: "Tier 1 - Quick (prediction history only)",
            RefreshTier.LIGHTWEIGHT: "Tier 2 - Lightweight (+ news & sentiment)",
            RefreshTier.FULL_RESTALE: "Tier 3 - Full Restale (+ stale warning)",
        }
        tier_detail = f"Research age: {staleness_days}d | Tier: {tier_names[tier]}"
        if history_block:
            tier_detail += f"\nPast predictions: {len(resolved_preds)} resolved"
        if news_context_block:
            tier_detail += f"\nNews headlines fetched: {len(headlines)}"

        console.print(Panel(
            tier_detail,
            title=f"Context Refresh: {agent.name}",
            border_style="magenta",
        ))

    # --- Prediction via single LLM call (first run) or debate (2nd+ run) ---
    def _run_step(label: str, fn):
        """Run fn() with a spinner, then print persistent done/failed line."""
        with console.status(f"  [cyan]{label}[/cyan]", spinner="dots"):
            result = fn()
        console.print(f"  [cyan]{label}[/cyan] [green]done[/green]")
        return result

    if is_first_run:
        # First run: single LLM call (original behavior)
        try:
            def _single_call():
                messages = [
                    ("system", system_prompt),
                    ("human", market_context),
                ]
                return llm.invoke(messages)

            response = _run_step(f"Analyzing {agent.ticker} with LLM...", _single_call)
            content = response.content

            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if not json_match:
                console.print(f"[red]Could not parse LLM response as JSON[/red]")
                console.print(f"[dim]{content}[/dim]")
                return None

            analysis = json.loads(json_match.group())
        except Exception as e:
            console.print(f"  [cyan]Analyzing {agent.ticker} with LLM...[/cyan] [red]failed[/red]")
            console.print(f"[red]Error during LLM analysis: {e}[/red]")
            return None
    else:
        # 2nd+ run: lightweight debate (Bull vs Bear vs Judge)
        from cybernetic.agents.debate import run_lightweight_debate

        # Wrap the debate so each step gets its own spinner + persistent line
        _pending_status = [None]

        def _step_callback(msg: str):
            """Called by debate before each step. We finish the previous spinner here."""
            # This is called INSIDE the debate, so we can't use console.status here.
            # Instead we track steps and print them between calls.
            _pending_status[0] = msg

        try:
            # Run each debate step individually with its own spinner
            from cybernetic.agents.debate import (
                _extract_section, _parse_judge_decision,
            )
            from cybernetic.research.agents.researchers.bull_researcher import create_bull_researcher
            from cybernetic.research.agents.researchers.bear_researcher import create_bear_researcher
            from cybernetic.research.agents.managers.research_manager import create_research_manager
            from cybernetic.research.agents.utils.memory import FinancialSituationMemory

            # Build debate state (same as run_lightweight_debate)
            market_report = market_context
            if history_block:
                market_report += f"\n\nPast Prediction History:\n{history_block}"
            sentiment_report = news_context_block if news_context_block else _extract_section(agent.research_report or "", "sentiment")
            news_report = news_context_block if news_context_block else _extract_section(agent.research_report or "", "news")
            fundamentals_report = _extract_section(agent.research_report or "", "fundamental")

            bull_memory = FinancialSituationMemory(name=f"{agent.ticker}_bull_debate")
            bear_memory = FinancialSituationMemory(name=f"{agent.ticker}_bear_debate")
            judge_memory = FinancialSituationMemory(name=f"{agent.ticker}_judge_debate")

            state = {
                "market_report": market_report,
                "sentiment_report": sentiment_report,
                "news_report": news_report,
                "fundamentals_report": fundamentals_report,
                "investment_debate_state": {
                    "history": "", "bull_history": "", "bear_history": "",
                    "current_response": "", "count": 0,
                },
            }

            bull_node = create_bull_researcher(llm, bull_memory)
            bear_node = create_bear_researcher(llm, bear_memory)
            judge_node = create_research_manager(llm, judge_memory)

            # Bull step
            def _bull():
                result = bull_node(state)
                state["investment_debate_state"] = result["investment_debate_state"]
            _run_step(f"Bull researcher arguing for {agent.ticker}...", _bull)

            # Bear step
            def _bear():
                result = bear_node(state)
                state["investment_debate_state"] = result["investment_debate_state"]
            _run_step(f"Bear researcher arguing against {agent.ticker}...", _bear)

            # Judge step
            def _judge():
                result = judge_node(state)
                state["investment_debate_state"] = result["investment_debate_state"]
                return result.get("investment_plan", "")
            judge_decision = _run_step(f"Judge evaluating arguments for {agent.ticker}...", _judge)

            direction, confidence, reasoning = _parse_judge_decision(judge_decision)
            analysis = {
                "direction": direction,
                "confidence": confidence,
                "reasoning": reasoning,
                "target_days": default_target_days,
            }
        except Exception as e:
            # Fall back to single LLM call if debate fails
            console.print(f"[yellow]Debate failed ({e}), falling back to single LLM call...[/yellow]")
            try:
                human_parts = [market_context]
                if history_block:
                    human_parts.append(history_block)
                if news_context_block:
                    human_parts.append(news_context_block)

                def _fallback():
                    messages = [
                        ("system", system_prompt),
                        ("human", "\n\n".join(human_parts)),
                    ]
                    return llm.invoke(messages)

                response = _run_step(f"Analyzing {agent.ticker} with LLM (fallback)...", _fallback)
                content = response.content

                json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
                if not json_match:
                    console.print(f"[red]Could not parse LLM response as JSON[/red]")
                    console.print(f"[dim]{content}[/dim]")
                    return None

                analysis = json.loads(json_match.group())
            except Exception as e2:
                console.print(f"  [cyan]Analyzing {agent.ticker} with LLM (fallback)...[/cyan] [red]failed[/red]")
                console.print(f"[red]Error during fallback LLM analysis: {e2}[/red]")
                return None

    # Create prediction
    direction = analysis.get("direction", "BULLISH").upper()
    confidence = min(max(float(analysis.get("confidence", 0.5)), 0.5), 0.95)
    reasoning = analysis.get("reasoning", "")
    target_days = int(analysis.get("target_days", default_target_days))
    target_date = (datetime.now() + timedelta(days=target_days)).date()

    # Resolve which ticker to trade
    if is_multi_ticker:
        chosen_ticker = analysis.get("ticker", "").strip().upper()
        if chosen_ticker not in ticker_market_data:
            chosen_ticker = next(iter(ticker_market_data))
        current_price = ticker_market_data[chosen_ticker]["current_price"]
    else:
        chosen_ticker = next(iter(ticker_market_data))

    # Parse position size from agent response
    # Single-ticker agents (max_positions=1) go all-in with available capital
    if agent.max_positions == 1:
        position_pct = 100.0
    else:
        position_pct = max(float(analysis.get("position_size", 10)), 5.0)
    dollar_amount = agent.portfolio_balance * (position_pct / 100.0)
    # Cap to available balance
    dollar_amount = min(dollar_amount, agent.portfolio_balance)
    fee = dollar_amount * 0.001  # 0.1% fee
    quantity = dollar_amount / current_price

    # Determine trade side based on direction
    side = "SHORT_SELL" if direction == "BEARISH" else "BUY"

    prediction = Prediction(
        agent_id=agent.id,
        ticker=chosen_ticker,
        direction=direction,
        confidence=confidence,
        reasoning=reasoning,
        entry_price=current_price,
        target_date=target_date,
        position_pct=position_pct,
        position_size=dollar_amount,
    )
    prediction = save_prediction(prediction)

    trade = Trade(
        prediction_id=prediction.id,
        agent_id=agent.id,
        side=side,
        ticker=chosen_ticker,
        price=current_price,
        quantity=quantity,
        fee=fee,
    )
    save_trade(trade)

    # Update portfolio balance
    new_balance = agent.portfolio_balance - dollar_amount - fee
    update_agent_balance(agent.id, new_balance)

    # Display result
    display_prediction_result(agent, prediction, trade, current_price)

    # Push to cybernetic.biz if requested
    if push_to_cybernetic:
        push_prediction_to_cybernetic(agent, prediction)

        # Comment on other agents' predictions (with timeout)
        from cybernetic.agents.commenter import run_comment_cycle
        import threading
        comment_result = [0]
        def _comment_task():
            comment_result[0] = run_comment_cycle(agent, llm, max_comments=1)
        t = threading.Thread(target=_comment_task, daemon=True)
        try:
            with console.status(f"  [cyan]Commenting on other predictions...[/cyan]", spinner="dots"):
                t.start()
                t.join(timeout=30)
            if t.is_alive():
                console.print(f"  [cyan]Commenting on other predictions...[/cyan] [yellow]timed out[/yellow]")
            elif comment_result[0]:
                n = comment_result[0]
                console.print(f"  [cyan]Commenting on other predictions...[/cyan] [green]done ({n} posted)[/green]")
            else:
                console.print(f"  [cyan]Commenting on other predictions...[/cyan] [dim]none[/dim]")
        except Exception as e:
            console.print(f"  [cyan]Commenting on other predictions...[/cyan] [dim]skipped: {e}[/dim]")

    return prediction


def display_prediction_result(agent: Agent, prediction: Prediction, trade: Trade, price: float):
    """Display a prediction result in the terminal."""
    direction_color = "green" if prediction.direction == "BULLISH" else "red"
    direction_emoji = "^" if prediction.direction == "BULLISH" else "v"

    table = Table(title=f"Prediction: {agent.name}", box=box.ROUNDED, border_style="cyan")
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("Ticker", agent.ticker)
    table.add_row("Direction", f"[{direction_color}]{direction_emoji} {prediction.direction}[/{direction_color}]")
    table.add_row("Confidence", f"{prediction.confidence:.0%}")
    table.add_row("Entry Price", f"${price:.2f}")
    table.add_row("Target Date", str(prediction.target_date))
    table.add_row("Trade Size", f"${trade.price * trade.quantity:.2f}")
    table.add_row("Fee", f"${trade.fee:.2f}")
    table.add_row("Reasoning", prediction.reasoning)

    console.print(table)


def _detect_asset_class(ticker: str) -> str:
    """Infer asset class from ticker symbol."""
    t = ticker.upper()
    if t.endswith("-USD") or t.endswith("USD"):
        return "crypto"
    if t.startswith("^"):
        return "stocks"
    commodity_tickers = {"GLD", "SLV", "USO", "UNG", "GC=F", "SI=F", "CL=F"}
    if t in commodity_tickers:
        return "commodities"
    forex_patterns = ("=X",)
    if any(t.endswith(p) for p in forex_patterns):
        return "forex"
    return "stocks"


def register_agent_on_cybernetic(agent: Agent) -> str:
    """Register agent on cybernetic.biz and persist the API key.

    If the agent name is already taken (409), appends a suffix and retries.
    Returns the API key string, or empty string on failure.
    """
    import httpx
    from cybernetic.storage.db import update_agent_api_key
    import random

    api_url = "https://cybernetic.biz/api/v1"
    name = agent.name

    for attempt in range(3):
        try:
            response = httpx.post(
                f"{api_url}/agents/register",
                json={
                    "name": name,
                    "description": agent.description or f"Trading agent for {agent.ticker}",
                },
                timeout=30.0,
            )
        except Exception as e:
            console.print(f"[yellow]Registration request failed: {e}[/yellow]")
            return ""

        if response.status_code == 200:
            body = response.json()
            api_key = body.get("data", body).get("api_key") or body.get("api_key")
            if not api_key:
                console.print(f"[yellow]No api_key in registration response[/yellow]")
                return ""
            # Persist the key so we don't re-register
            update_agent_api_key(agent.id, api_key)
            console.print(f"[green]Registered '{name}' on cybernetic.biz[/green]")
            return api_key

        if response.status_code == 409:
            suffix = random.randint(10, 99)
            name = f"{agent.name}-{suffix}"
            console.print(f"[yellow]Name taken, retrying as '{name}'...[/yellow]")
            continue

        console.print(f"[yellow]Registration failed: {response.status_code} {response.text}[/yellow]")
        return ""

    console.print("[yellow]Could not register agent (name conflicts)[/yellow]")
    return ""


def push_prediction_to_cybernetic(agent: Agent, prediction: Prediction):
    """Push a prediction to cybernetic.biz API.

    Auto-registers the agent if it doesn't have an API key yet.
    Each agent gets its own key from POST /api/v1/agents/register.
    """
    import httpx
    import time
    from datetime import timezone

    api_url = "https://cybernetic.biz/api/v1"
    max_retries = 3
    retry_delay = 2

    # Get or create API key for this agent
    api_key = agent.cybernetic_api_key
    if not api_key:
        api_key = register_agent_on_cybernetic(agent)
        if not api_key:
            return

    asset_class = _detect_asset_class(prediction.ticker)
    dollar_amount = max(500.0, agent.portfolio_balance * 0.05)

    # Sanitize ticker for API: strip chars not in [A-Za-z0-9/.=-]
    api_ticker = re.sub(r"[^A-Za-z0-9/.=\-]", "", prediction.ticker)

    # Format target_date as ISO 8601 UTC datetime (API requires "2026-02-22T14:30:45Z")
    if prediction.target_date:
        td = datetime.combine(prediction.target_date, datetime.min.time(), tzinfo=timezone.utc)
        target_date_str = td.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        target_date_str = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Ensure reasoning meets API minimum (10 chars) and direction is valid
    reasoning = (prediction.reasoning or "").strip()
    if len(reasoning) < 10:
        reasoning = f"Agent {agent.name} predicts {prediction.direction} on {prediction.ticker}. {reasoning}"
    direction = prediction.direction.upper()
    if direction not in ("BULLISH", "BEARISH"):
        direction = "BULLISH" if direction == "BUY" else "BEARISH" if direction == "SELL" else "BULLISH"
    confidence = max(0.0, min(1.0, prediction.confidence))

    payload = {
        "ticker": api_ticker,
        "asset_class": asset_class,
        "direction": direction,
        "confidence": confidence,
        "reasoning": reasoning[:2000],
        "target_date": target_date_str,
        "dollar_amount": dollar_amount,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    for attempt in range(1, max_retries + 1):
        try:
            response = httpx.post(
                f"{api_url}/predictions",
                headers=headers,
                json=payload,
                timeout=30.0,
            )
            if response.status_code == 200:
                from cybernetic.storage.db import mark_prediction_pushed
                mark_prediction_pushed(prediction.id)
                console.print("[green]Prediction pushed to cybernetic.biz[/green]")
                return
            else:
                console.print(f"[yellow]Push attempt {attempt}: {response.status_code} {response.text}[/yellow]")
                if attempt == 1:
                    console.print(f"[dim]Payload: {json.dumps(payload, indent=2)}[/dim]")
        except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            console.print(f"[yellow]Push attempt {attempt} failed: {e}[/yellow]")

        if attempt < max_retries:
            time.sleep(retry_delay)

    console.print("[yellow]Failed to push prediction after retries.[/yellow]")
