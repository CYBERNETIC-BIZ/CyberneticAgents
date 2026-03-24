"""Create-from-prompt CLI flow: generate a full agent from a strategy description."""
import json

import questionary
from rich.console import Console

from cybernetic.cli.utils import ask, QMARK, TEMP_LABELS, display_agent_config

console = Console()


def _edit_config(cfg: dict):
    """Walk through each field with pre-filled prompts for editing.

    Returns the edited config dict, or None if user pressed ESC at any point.
    """
    result = ask(questionary.text("Name:", qmark=QMARK, default=cfg.get("name", "")))
    if result is None:
        return None
    cfg["name"] = result or cfg["name"]

    result = ask(questionary.text("Ticker:", qmark=QMARK, default=cfg.get("ticker", "")))
    if result is None:
        return None
    cfg["ticker"] = (result or cfg["ticker"]).strip().upper()

    result = ask(questionary.text("Description:", qmark=QMARK, default=cfg.get("description", "")))
    if result is None:
        return None
    cfg["description"] = result or cfg.get("description", "")

    from cybernetic.cli.theme import t as theme
    all_tools = ["market", "social", "news", "fundamentals"]
    current_tools = cfg.get("tools", [])
    result = ask(questionary.checkbox(
        "Tools:",
        qmark=QMARK,
        choices=[questionary.Choice(tool, checked=(tool in current_tools)) for tool in all_tools],
        instruction="\n- Press Space to select/unselect\n- Press 'a' to toggle all\n- Press Enter when done",
        style=questionary.Style([
            ("checkbox-selected", theme("menu_checkbox")),
            ("selected", theme("menu_selected")),
            ("highlighted", "noinherit"),
            ("pointer", "noinherit"),
        ]),
    ))
    if result is None:
        return None
    cfg["tools"] = result or current_tools

    result = ask(questionary.select(
        "Target days:",
        qmark=QMARK,
        choices=[
            questionary.Choice(str(d), value=d) for d in [1, 3, 5, 7, 14, 30]
        ],
        default=cfg.get("target_days", 7),
    ))
    if result is None:
        return None
    cfg["target_days"] = result or cfg.get("target_days", 7)

    default_max = 1 if len(cfg.get("ticker", "").split(",")) == 1 else cfg.get("max_positions", 5)
    result = ask(questionary.text(
        "Max positions:", qmark=QMARK, default=str(default_max)
    ))
    if result is None:
        return None
    cfg["max_positions"] = int(result or "1")

    result = ask(questionary.text("Personality:", qmark=QMARK, default=cfg.get("personality", "")))
    if result is None:
        return None
    cfg["personality"] = result or ""

    current_temp = cfg.get("analysis_temperature", 0.7)
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
        default=cfg.get("analysis_system_prompt", ""),
    ))
    if result is None:
        return None
    cfg["analysis_system_prompt"] = result or cfg.get("analysis_system_prompt", "")

    return cfg


def _flush_stdin() -> None:
    """Discard any buffered keystrokes so they don't leak into the next prompt."""
    import sys
    try:
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except (ImportError, termios.error):
        pass


def run_create_from_prompt() -> None:
    """Interactive create-from-prompt flow."""
    _flush_stdin()
    console.print("\n[bold cyan]Create Agent from Prompt[/bold cyan]")
    console.print("[dim]e.g. conservative value investor focused on tech stocks[/dim]")
    from cybernetic.cli.theme import t as theme
    strategy = ask(questionary.text(
        "Strategy:",
        qmark=QMARK,
        style=questionary.Style([
            ("text", theme("menu_accent")),
            ("highlighted", "noinherit"),
        ]),
    ))

    if not strategy or not strategy.strip():
        return  # ESC or empty → back to menu

    # Heavy imports deferred until after the user has typed their strategy
    from cybernetic.cli.utils import select_llm_provider, select_shallow_thinking_agent
    from cybernetic.config import get_config, set_config
    from cybernetic.agents.think import think_agent_config
    from cybernetic.agents.ticker import resolve_tickers
    from cybernetic.agents.names import validate_agent_name, generate_funny_name
    from cybernetic.storage.db import save_agent
    from cybernetic.storage.models import Agent

    # Step 2: Select LLM provider
    result = select_llm_provider()
    if result is None:
        return  # ESC → back to menu
    provider_name, base_url = result
    config = get_config()
    config["llm_provider"] = provider_name.lower()
    config["backend_url"] = base_url
    set_config(config)

    # Step 3: Select model
    model = select_shallow_thinking_agent(provider_name.lower())
    if model is None:
        return  # ESC → back to menu
    config["quick_think_llm"] = model
    set_config(config)

    while True:
        # Step 4: Generate config with spinner
        with console.status("[cyan]Generating agent config...[/cyan]"):
            try:
                cfg = think_agent_config(strategy.strip(), config)
            except Exception as e:
                console.print(f"[red]Error generating config: {e}[/red]")
                retry = ask(questionary.confirm("Try again?", qmark=QMARK, default=True))
                if retry:
                    continue
                return

        # Step 5: Display config
        console.print()
        display_agent_config(cfg)

        # Step 6: Accept / Edit / Regenerate
        action = ask(questionary.select(
            "What would you like to do?",
            qmark=QMARK,
            choices=[
                questionary.Choice("Accept", value="accept"),
                questionary.Choice("Edit", value="edit"),
                questionary.Choice("Regenerate", value="regen"),
                questionary.Choice("Cancel", value="cancel"),
            ],
            instruction="\n- Use arrow keys to navigate\n- Press Enter to select\n- Press ESC to go back",
        ))

        if action == "cancel" or action is None:
            console.print("[dim]Cancelled.[/dim]")
            return
        elif action == "regen":
            new_strategy = ask(questionary.text(
                "Strategy (Enter to reuse previous):",
                qmark=QMARK,
                default=strategy.strip(),
            ))
            if new_strategy is None:
                return  # ESC → back to menu
            if new_strategy.strip():
                strategy = new_strategy
            continue
        elif action == "edit":
            edited = _edit_config(cfg)
            if edited is None:
                continue  # ESC during edit → back to accept/edit/regen menu
            cfg = edited
            display_agent_config(cfg)

        # Accept flow: validate ticker
        console.print()
        with console.status(f"[cyan]Finding ticker for '{cfg['ticker']}'...[/cyan]"):
            try:
                resolved_ticker = resolve_tickers(cfg["ticker"], config=config)
                cfg["ticker"] = resolved_ticker
            except ValueError as e:
                console.print(f"[red]Ticker validation failed: {e}[/red]")
                new_ticker = ask(questionary.text("Enter a valid ticker:", qmark=QMARK))
                if new_ticker:
                    cfg["ticker"] = new_ticker.strip().upper()
                else:
                    return

        # Validate name
        name = cfg.get("name", "").lower().strip()
        if not validate_agent_name(name):
            name = generate_funny_name()
            console.print(f"  [yellow]Auto-generated name:[/yellow] {name}")
        cfg["name"] = name

        # Step 7: Save to database
        agent = Agent(
            id=cfg["name"],
            name=cfg["name"],
            ticker=cfg["ticker"],
            persona_json=json.dumps(cfg),
            research_report="",
            description=cfg.get("description", ""),
            tools=json.dumps(cfg.get("tools", [])),
            analysis_system_prompt=cfg.get("analysis_system_prompt", ""),
            comment_system_prompt=cfg.get("comment_system_prompt", ""),
            analysis_temperature=cfg.get("analysis_temperature", 0.7),
            comment_temperature=cfg.get("comment_temperature", 0.8),
            target_days=cfg.get("target_days", 7),
            max_positions=cfg.get("max_positions", 5),
            personality=cfg.get("personality", ""),
            direction_bias=cfg.get("direction_bias", "bullish"),
            created_from="prompt",
        )
        saved = save_agent(agent)

        # Register on cybernetic.biz immediately
        from cybernetic.agents.runner import register_agent_on_cybernetic
        register_agent_on_cybernetic(saved)

        console.print(f"\n[green]Agent created: {saved.id}[/green]")
        console.print(f"[dim]Ticker: {saved.ticker} | Portfolio: ${saved.portfolio_balance:,.2f}[/dim]")

        # Offer to run immediately
        run_now = ask(questionary.confirm("Run agent now?", qmark=QMARK, default=True))
        if run_now:
            from cybernetic.agents.runner import run_agent_once
            run_agent_once(saved.id, push_to_cybernetic=True)

        console.input("\n[dim]Press Enter to continue...[/dim]")
        return
