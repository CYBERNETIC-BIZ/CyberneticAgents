"""My Agents flow: browse, view details, edit, run, and resolve agents."""
import json

import questionary
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from cybernetic.cli.utils import ask, QMARK, TEMP_LABELS

console = Console()

def _menu_style():
    from cybernetic.cli.theme import t
    return questionary.Style([
        ("selected", t("menu_selected")),
        ("highlighted", t("menu_highlighted")),
        ("pointer", t("menu_pointer")),
        ("qmark", t("menu_qmark")),
        ("question", t("menu_question")),
    ])


def _agent_card(agent, stats) -> Panel:
    """Build a Rich Panel card showing full agent configuration."""
    from cybernetic.storage.db import get_open_position_cost

    tools = json.loads(agent.tools) if agent.tools else []
    tools_str = ", ".join(tools) if tools else "none"

    temp = agent.analysis_temperature
    temp_label = TEMP_LABELS.get(temp, f"{temp}")

    open_cost = get_open_position_cost(agent.id)
    total_value = agent.portfolio_balance + open_cost
    pnl = total_value - 10000
    pnl_color = "green" if pnl >= 0 else "red"

    # Config table
    config_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2), expand=True)
    config_table.add_column("Field", style="bold green", width=20)
    config_table.add_column("Value")

    config_table.add_row("Ticker", agent.ticker)
    config_table.add_row("Direction Bias", agent.direction_bias)
    config_table.add_row("Created From", agent.created_from)
    config_table.add_row("Created", str(agent.created_at)[:10] if agent.created_at else "N/A")
    config_table.add_row("Tools", tools_str)
    config_table.add_row("Target Days", str(agent.target_days))
    config_table.add_row("Max Positions", str(agent.max_positions))
    config_table.add_row("Temperature", f"{temp} ({temp_label})")
    config_table.add_row(
        "Portfolio",
        f"[{pnl_color}]${total_value:,.2f} ({pnl:+,.2f})[/{pnl_color}]",
    )
    accuracy_str = (
        f"{stats['accuracy']:.0f}% ({stats['correct']}/{stats['resolved']})"
        if stats["resolved"] > 0
        else "N/A"
    )
    config_table.add_row("Accuracy", accuracy_str)
    config_table.add_row("Predictions", f"{stats['total']} total, {stats['pending']} pending")

    # Description / personality section
    sections = []
    if agent.description:
        sections.append(Text(f"Description: {agent.description}", style="dim"))
    if agent.personality:
        sections.append(Text(f"Personality: {agent.personality}", style="dim"))

    # System prompt (truncated)
    prompt = agent.analysis_system_prompt or ""
    if prompt:
        preview = prompt[:500]
        if len(prompt) > 500:
            preview += "..."
        sections.append(Text())
        sections.append(Text("System Prompt:", style="bold green"))
        sections.append(Text(preview, style="dim"))

    from cybernetic.cli.theme import t as theme
    return Panel(
        Group(config_table, Text(), *sections),
        title=f"[bold]{agent.name}[/bold]",
        subtitle=f"{agent.ticker} | {agent.direction_bias}",
        border_style=theme("border_report"),
        padding=(1, 2),
    )


def _edit_agent(agent):
    """Edit an agent's configuration fields and persist changes."""
    from cybernetic.storage.db import save_agent
    from cybernetic.cli.theme import t

    # Build a config dict from the agent's current fields
    tools = json.loads(agent.tools) if agent.tools else []
    cfg = {
        "description": agent.description,
        "tools": tools,
        "target_days": agent.target_days,
        "max_positions": agent.max_positions,
        "personality": agent.personality,
        "analysis_temperature": agent.analysis_temperature,
        "analysis_system_prompt": agent.analysis_system_prompt,
    }

    # Walk through fields one by one (ESC at any point cancels)
    result = ask(questionary.text("Description:", qmark=QMARK, default=cfg["description"]))
    if result is None:
        return None
    cfg["description"] = result or cfg["description"]

    all_tools = ["market", "social", "news", "fundamentals"]
    result = ask(questionary.checkbox(
        "Tools:",
        qmark=QMARK,
        choices=[questionary.Choice(t, checked=(t in cfg["tools"])) for t in all_tools],
        instruction="\n- Press Space to select/unselect\n- Press 'a' to toggle all\n- Press Enter when done",
        style=questionary.Style([
            ("checkbox-selected", t("menu_checkbox")),
            ("selected", t("menu_selected")),
            ("highlighted", "noinherit"),
            ("pointer", "noinherit"),
        ]),
    ))
    if result is None:
        return None
    cfg["tools"] = result or cfg["tools"]

    result = ask(questionary.select(
        "Target days:",
        qmark=QMARK,
        choices=[questionary.Choice(str(d), value=d) for d in [1, 3, 5, 7, 14, 30]],
        default=cfg["target_days"],
    ))
    if result is None:
        return None
    cfg["target_days"] = result or cfg["target_days"]

    result = ask(questionary.text(
        "Max positions:", qmark=QMARK, default=str(cfg["max_positions"]),
    ))
    if result is None:
        return None
    cfg["max_positions"] = int(result or "5")

    result = ask(questionary.text("Personality:", qmark=QMARK, default=cfg["personality"]))
    if result is None:
        return None
    cfg["personality"] = result or ""

    current_temp = cfg["analysis_temperature"]
    snapped_temp = min(TEMP_LABELS.keys(), key=lambda k: abs(k - current_temp))
    result = ask(questionary.select(
        "Analysis temperature:",
        qmark=QMARK,
        choices=[
            questionary.Choice(f"{label} ({v})", value=v) for v, label in TEMP_LABELS.items()
        ],
        default=snapped_temp,
    ))
    if result is None:
        return None
    cfg["analysis_temperature"] = result if result is not None else 0.7

    result = ask(questionary.text(
        "System prompt (Enter to keep current):",
        qmark=QMARK,
        default=cfg["analysis_system_prompt"],
    ))
    if result is None:
        return None
    cfg["analysis_system_prompt"] = result or cfg["analysis_system_prompt"]

    # Apply changes to agent and save
    agent.description = cfg["description"]
    agent.tools = json.dumps(cfg["tools"])
    agent.target_days = cfg["target_days"]
    agent.max_positions = cfg["max_positions"]
    agent.personality = cfg["personality"]
    agent.analysis_temperature = cfg["analysis_temperature"]
    agent.analysis_system_prompt = cfg["analysis_system_prompt"]

    # Update persona_json to stay in sync
    try:
        persona = json.loads(agent.persona_json)
    except (json.JSONDecodeError, TypeError):
        persona = {}
    persona.update(cfg)
    agent.persona_json = json.dumps(persona)

    save_agent(agent)
    return agent


def _resolve_agent_predictions(agent_id: str):
    """Resolve only this agent's pending predictions."""
    import yfinance as yf
    from cybernetic.storage.db import (
        get_agent_predictions, resolve_prediction,
        save_trade, get_agent, update_agent_balance,
        get_trade_for_prediction,
    )
    from cybernetic.storage.models import Trade

    FEE_RATE = 0.001
    pending = [p for p in get_agent_predictions(agent_id, pending_only=True)
               if p.target_date and p.target_date <= __import__("datetime").date.today()]

    if not pending:
        console.print("[cyan]No pending predictions to resolve for this agent.[/cyan]")
        return

    console.print(f"[cyan]Resolving {len(pending)} predictions...[/cyan]")

    from cybernetic.cli.theme import t as theme
    results_table = Table(title="Resolved", box=box.ROUNDED, border_style=theme("primary"))
    results_table.add_column("Ticker")
    results_table.add_column("Direction")
    results_table.add_column("Entry")
    results_table.add_column("Exit")
    results_table.add_column("Result")
    results_table.add_column("P&L")

    for pred in pending:
        try:
            ticker_data = yf.Ticker(pred.ticker)
            hist = ticker_data.history(period="5d")
            if hist.empty:
                continue

            exit_price = hist["Close"].iloc[-1]
            price_moved_up = exit_price > pred.entry_price

            if pred.direction == "BULLISH":
                result = "correct" if price_moved_up else "incorrect"
            else:
                result = "correct" if not price_moved_up else "incorrect"

            resolve_prediction(pred.id, result, exit_price)

            agent = get_agent(pred.agent_id)
            if not agent:
                continue

            open_side = "SHORT_SELL" if pred.direction == "BEARISH" else "BUY"
            open_trade = get_trade_for_prediction(pred.id, open_side)
            if not open_trade:
                continue

            quantity = open_trade.quantity

            if pred.direction == "BEARISH":
                effective_price = 2 * pred.entry_price - exit_price
                sell_value = effective_price * quantity
                close_side = "SHORT_COVER"
                trade_price = effective_price
            else:
                sell_value = exit_price * quantity
                close_side = "SELL"
                trade_price = exit_price

            fee = sell_value * FEE_RATE
            trade = Trade(
                prediction_id=pred.id,
                agent_id=pred.agent_id,
                side=close_side,
                ticker=pred.ticker,
                price=trade_price,
                quantity=quantity,
                fee=fee,
            )
            save_trade(trade)

            new_balance = agent.portfolio_balance + sell_value - fee
            update_agent_balance(pred.agent_id, new_balance)

            if pred.direction == "BEARISH":
                pnl_pct = ((pred.entry_price - exit_price) / pred.entry_price) * 100
            else:
                pnl_pct = ((exit_price - pred.entry_price) / pred.entry_price) * 100

            result_color = "green" if result == "correct" else "red"
            results_table.add_row(
                pred.ticker,
                pred.direction,
                f"${pred.entry_price:.2f}",
                f"${exit_price:.2f}",
                f"[{result_color}]{result.upper()}[/{result_color}]",
                f"[{result_color}]{pnl_pct:+.2f}%[/{result_color}]",
            )
        except Exception as e:
            console.print(f"[yellow]Error resolving {pred.ticker}: {e}[/yellow]")

    console.print(results_table)


def my_agents_flow():
    """Interactive My Agents flow: list, view, edit, run, resolve."""
    from cybernetic.storage.db import list_agents, get_agent, get_agent_stats

    while True:
        agents = list_agents()
        if not agents:
            console.print("[yellow]No agents found. Create one first.[/yellow]")
            return

        # Agent list selection — clean format: name (ticker)
        # Icon prefix: research vs prompt origin
        def _label(a):
            icon = "🔬" if a.created_from == "research" else "🤖"
            return f"{icon} {a.name} ({a.ticker})"

        choices = [
            questionary.Choice(_label(a), value=a.id)
            for a in agents
        ]
        choices.append(questionary.Choice("Back", value="back"))

        selected = ask(questionary.select(
            "My Agents:",
            qmark=QMARK,
            choices=choices,
            instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
            style=_menu_style(),
        ))

        if selected is None or selected == "back":
            return

        # Per-agent sub-menu loop
        while True:
            agent = get_agent(selected)
            if not agent:
                console.print(f"[red]Agent '{selected}' not found.[/red]")
                break

            action = ask(questionary.select(
                f"{agent.name} ({agent.ticker}):",
                qmark=QMARK,
                choices=[
                    questionary.Choice("View Details", value="view"),
                    questionary.Choice("Edit", value="edit"),
                    questionary.Choice("Run Agent", value="run"),
                    questionary.Choice("Resolve Predictions", value="resolve"),
                    questionary.Choice("Back", value="back"),
                ],
                instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
                style=_menu_style(),
            ))

            if action is None or action == "back":
                break

            if action == "view":
                stats = get_agent_stats(agent.id)
                console.print()
                console.print(_agent_card(agent, stats))
                console.print()

            elif action == "edit":
                updated = _edit_agent(agent)
                if updated:
                    console.print(f"[green]Agent '{updated.name}' updated.[/green]")
                else:
                    console.print("[dim]Edit cancelled.[/dim]")

            elif action == "run":
                from cybernetic.agents.runner import run_agent_once
                run_agent_once(agent.id)

            elif action == "resolve":
                _resolve_agent_predictions(agent.id)
