import questionary
from typing import List, Optional, Tuple, Dict
from rich.console import Console
from rich.table import Table
from rich import box

from cybernetic.cli.models import AnalystType

console = Console()
QMARK = "›"

ANALYST_ORDER = [
    ("Market Analyst", AnalystType.MARKET),
    ("Social Media Analyst", AnalystType.SOCIAL),
    ("News Analyst", AnalystType.NEWS),
    ("Fundamentals Analyst", AnalystType.FUNDAMENTALS),
]


def _patch_escape(question):
    """Add ESC key binding to a questionary Question so pressing ESC cancels (returns None)."""
    from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings

    esc_kb = KeyBindings()

    @esc_kb.add('escape', eager=True)
    def _(event):
        event.app.exit(exception=KeyboardInterrupt())

    app = question.application
    if app.key_bindings is not None:
        app.key_bindings = merge_key_bindings([app.key_bindings, esc_kb])
    else:
        app.key_bindings = esc_kb

    return question


def ask(question):
    """Ask a questionary question with ESC-to-go-back support.

    Returns None on ESC or Ctrl+C.
    """
    return _patch_escape(question).ask()


def get_ticker() -> Optional[str]:
    """Prompt the user to enter a ticker symbol, with alias resolution and yfinance validation."""
    from cybernetic.agents.ticker import normalize_ticker, resolve_tickers
    from cybernetic.config import get_config
    from cybernetic.cli.theme import t

    while True:
        raw = ask(questionary.text(
            "Enter the ticker symbol to analyze:",
            qmark=QMARK,
            validate=lambda x: len(x.strip()) > 0 or "Please enter a valid ticker symbol.",
            style=questionary.Style(
                [
                    ("text", t("menu_text")),
                    ("highlighted", "noinherit"),
                ]
            ),
        ))

        if raw is None:
            return None

        raw = raw.strip()
        if not raw:
            continue

        alias_result = normalize_ticker(raw)

        try:
            config = get_config()
            with console.status(f"[cyan]Finding ticker for '{raw}'...[/cyan]"):
                resolved = resolve_tickers(raw, config=config)

            # Show resolution feedback
            if resolved != raw.upper():
                source = "alias" if alias_result == resolved else "LLM"
                console.print(f"  [green]Resolved[/green] '{raw}' -> [bold]{resolved}[/bold] (via {source})")
            else:
                console.print(f"  [green]Validated[/green] [bold]{resolved}[/bold]")

            return resolved
        except ValueError as e:
            console.print(f"  [red]{e}[/red]")
            console.print("  [dim]Please try again.[/dim]")


def get_analysis_date() -> Optional[str]:
    """Prompt the user to enter a date in YYYY-MM-DD format with future-date check."""
    import re
    from datetime import datetime
    from cybernetic.cli.theme import t

    def validate_date(date_str: str) -> bool:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return False
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return True
        except ValueError:
            return False

    while True:
        date = ask(questionary.text(
            "Enter the analysis date (YYYY-MM-DD):",
            qmark=QMARK,
            default=datetime.now().strftime("%Y-%m-%d"),
            validate=lambda x: validate_date(x.strip())
            or "Please enter a valid date in YYYY-MM-DD format.",
            style=questionary.Style(
                [
                    ("text", t("menu_text")),
                    ("highlighted", "noinherit"),
                ]
            ),
        ))

        if date is None:
            return None

        analysis_date = datetime.strptime(date.strip(), "%Y-%m-%d")
        if analysis_date.date() > datetime.now().date():
            console.print("[red]Error: Analysis date cannot be in the future[/red]")
            continue

        return date.strip()


def select_analysts() -> Optional[List[AnalystType]]:
    """Select analysts using an interactive checkbox."""
    from cybernetic.cli.theme import t
    choices = ask(questionary.checkbox(
        "Select Your [Analysts Team]:",
        qmark=QMARK,
        choices=[
            questionary.Choice(display, value=value) for display, value in ANALYST_ORDER
        ],
        instruction="\n- Press Space to select/unselect analysts\n- Press 'a' to select/unselect all\n- Press Enter when done\n- Press ESC to go back",
        validate=lambda x: len(x) > 0 or "You must select at least one analyst.",
        style=questionary.Style(
            [
                ("checkbox-selected", t("menu_checkbox")),
                ("selected", t("menu_selected")),
                ("highlighted", "noinherit"),
                ("pointer", "noinherit"),
            ]
        ),
    ))

    if not choices:
        return None

    return choices


def select_research_depth() -> Optional[int]:
    """Select research depth using an interactive selection."""
    from cybernetic.cli.theme import t

    # Define research depth options with their corresponding values
    DEPTH_OPTIONS = [
        ("Shallow - Quick research, few debate and strategy discussion rounds", 1),
        ("Medium - Middle ground, moderate debate rounds and strategy discussion", 3),
        ("Deep - Comprehensive research, in depth debate and strategy discussion", 5),
    ]

    choice = ask(questionary.select(
        "Select Your [Research Depth]:",
        qmark=QMARK,
        choices=[
            questionary.Choice(display, value=value) for display, value in DEPTH_OPTIONS
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select\n- Press ESC to go back",
        style=questionary.Style(
            [
                ("selected", t("menu_accent")),
                ("highlighted", t("menu_accent")),
                ("pointer", t("menu_accent")),
            ]
        ),
    ))

    if choice is None:
        return None

    return choice


def _get_ollama_choices() -> list:
    """Auto-detect Ollama models, ensuring server is running first."""
    from cybernetic.llm.ollama import ensure_ollama, get_model_choices
    ok, msg = ensure_ollama()
    if not ok:
        console.print(f"[red]{msg}[/red]")
        return [("No models available", "")]
    if msg == "Ollama started automatically":
        console.print(f"[dim]{msg}[/dim]")
    return get_model_choices()


def select_shallow_thinking_agent(provider) -> Optional[str]:
    """Select shallow thinking llm engine using an interactive selection."""
    from cybernetic.cli.theme import t

    # Define shallow thinking llm engine options with their corresponding model names
    SHALLOW_AGENT_OPTIONS = {
        "openai": [
            ("GPT-5 Mini - Cost-optimized reasoning", "gpt-5-mini"),
            ("GPT-5 Nano - Ultra-fast, high-throughput", "gpt-5-nano"),
            ("GPT-5.2 - Latest flagship", "gpt-5.2"),
            ("GPT-5.1 - Flexible reasoning", "gpt-5.1"),
            ("GPT-4.1 - Smartest non-reasoning, 1M context", "gpt-4.1"),
        ],
        "anthropic": [
            ("Claude Haiku 4.5 - Fast + extended thinking", "claude-haiku-4-5"),
            ("Claude Sonnet 4.5 - Best for agents/coding", "claude-sonnet-4-5"),
            ("Claude Sonnet 4 - High-performance", "claude-sonnet-4-20250514"),
        ],
        "google": [
            ("Gemini 3 Flash - Next-gen fast", "gemini-3-flash-preview"),
            ("Gemini 2.5 Flash - Balanced, recommended", "gemini-2.5-flash"),
            ("Gemini 3 Pro - Reasoning-first", "gemini-3-pro-preview"),
            ("Gemini 2.5 Flash Lite - Fast, low-cost", "gemini-2.5-flash-lite"),
        ],
        "xai": [
            ("Grok 4.1 Fast (Non-Reasoning) - Speed optimized, 2M ctx", "grok-4-1-fast-non-reasoning"),
            ("Grok 4 Fast (Non-Reasoning) - Speed optimized", "grok-4-fast-non-reasoning"),
            ("Grok 4.1 Fast (Reasoning) - High-performance, 2M ctx", "grok-4-1-fast-reasoning"),
            ("Grok 4 Fast (Reasoning) - High-performance", "grok-4-fast-reasoning"),
        ],
        "openrouter": [
            ("NVIDIA Nemotron 3 Nano 30B (free)", "nvidia/nemotron-3-nano-30b-a3b:free"),
            ("Z.AI GLM 4.5 Air (free)", "z-ai/glm-4.5-air:free"),
        ],
    }

    if provider.lower() == "ollama":
        options = _get_ollama_choices()
    else:
        options = SHALLOW_AGENT_OPTIONS[provider.lower()]

    choice = ask(questionary.select(
        "Select Your [Quick-Thinking LLM Engine]:",
        qmark=QMARK,
        choices=[
            questionary.Choice(display, value=value)
            for display, value in options
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select\n- Press ESC to go back",
        style=questionary.Style(
            [
                ("selected", t("menu_accent2")),
                ("highlighted", t("menu_accent2")),
                ("pointer", t("menu_accent2")),
            ]
        ),
    ))

    if choice is None:
        return None

    return choice


def select_deep_thinking_agent(provider) -> Optional[str]:
    """Select deep thinking llm engine using an interactive selection."""
    from cybernetic.cli.theme import t

    # Define deep thinking llm engine options with their corresponding model names
    DEEP_AGENT_OPTIONS = {
        "openai": [
            ("GPT-5.2 - Latest flagship", "gpt-5.2"),
            ("GPT-5.1 - Flexible reasoning", "gpt-5.1"),
            ("GPT-5 - Advanced reasoning", "gpt-5"),
            ("GPT-4.1 - Smartest non-reasoning, 1M context", "gpt-4.1"),
            ("GPT-5 Mini - Cost-optimized reasoning", "gpt-5-mini"),
            ("GPT-5 Nano - Ultra-fast, high-throughput", "gpt-5-nano"),
        ],
        "anthropic": [
            ("Claude Sonnet 4.5 - Best for agents/coding", "claude-sonnet-4-5"),
            ("Claude Opus 4.5 - Premium, max intelligence", "claude-opus-4-5"),
            ("Claude Opus 4.1 - Most capable model", "claude-opus-4-1-20250805"),
            ("Claude Haiku 4.5 - Fast + extended thinking", "claude-haiku-4-5"),
            ("Claude Sonnet 4 - High-performance", "claude-sonnet-4-20250514"),
        ],
        "google": [
            ("Gemini 3 Pro - Reasoning-first", "gemini-3-pro-preview"),
            ("Gemini 3 Flash - Next-gen fast", "gemini-3-flash-preview"),
            ("Gemini 2.5 Flash - Balanced, recommended", "gemini-2.5-flash"),
        ],
        "xai": [
            ("Grok 4.1 Fast (Reasoning) - High-performance, 2M ctx", "grok-4-1-fast-reasoning"),
            ("Grok 4 Fast (Reasoning) - High-performance", "grok-4-fast-reasoning"),
            ("Grok 4 - Flagship model", "grok-4-0709"),
            ("Grok 4.1 Fast (Non-Reasoning) - Speed optimized, 2M ctx", "grok-4-1-fast-non-reasoning"),
            ("Grok 4 Fast (Non-Reasoning) - Speed optimized", "grok-4-fast-non-reasoning"),
        ],
        "openrouter": [
            ("Z.AI GLM 4.5 Air (free)", "z-ai/glm-4.5-air:free"),
            ("NVIDIA Nemotron 3 Nano 30B (free)", "nvidia/nemotron-3-nano-30b-a3b:free"),
        ],
    }

    if provider.lower() == "ollama":
        options = _get_ollama_choices()
    else:
        options = DEEP_AGENT_OPTIONS[provider.lower()]

    choice = ask(questionary.select(
        "Select Your [Deep-Thinking LLM Engine]:",
        qmark=QMARK,
        choices=[
            questionary.Choice(display, value=value)
            for display, value in options
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select\n- Press ESC to go back",
        style=questionary.Style(
            [
                ("selected", t("menu_accent2")),
                ("highlighted", t("menu_accent2")),
                ("pointer", t("menu_accent2")),
            ]
        ),
    ))

    if choice is None:
        return None

    return choice


def select_llm_provider() -> Optional[tuple]:
    """Select the LLM provider using interactive selection."""
    from cybernetic.cli.theme import t
    BASE_URLS = [
        ("OpenAI", "https://api.openai.com/v1"),
        ("Google", "https://generativelanguage.googleapis.com/v1"),
        ("Anthropic", "https://api.anthropic.com/"),
        ("xAI", "https://api.x.ai/v1"),
        ("Openrouter", "https://openrouter.ai/api/v1"),
        ("Ollama", "http://localhost:11434/v1"),
    ]

    choice = ask(questionary.select(
        "Select your LLM Provider:",
        qmark=QMARK,
        choices=[
            questionary.Choice(display, value=(display, value))
            for display, value in BASE_URLS
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select\n- Press ESC to go back",
        style=questionary.Style(
            [
                ("selected", t("menu_accent2")),
                ("highlighted", t("menu_accent2")),
                ("pointer", t("menu_accent2")),
            ]
        ),
    ))

    if choice is None:
        return None

    display_name, url = choice

    return display_name, url


def ask_openai_reasoning_effort() -> Optional[str]:
    """Ask for OpenAI reasoning effort level."""
    from cybernetic.cli.theme import t
    choices = [
        questionary.Choice("Medium (Default)", "medium"),
        questionary.Choice("High (More thorough)", "high"),
        questionary.Choice("Low (Faster)", "low"),
    ]
    return ask(questionary.select(
        "Select Reasoning Effort:",
        qmark=QMARK,
        choices=choices,
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select\n- Press ESC to go back",
        style=questionary.Style([
            ("selected", t("menu_accent2")),
            ("highlighted", t("menu_accent2")),
            ("pointer", t("menu_accent2")),
        ]),
    ))


def ask_gemini_thinking_config() -> Optional[str]:
    """Ask for Gemini thinking configuration.

    Returns thinking_level: "high" or "minimal".
    Client maps to appropriate API param based on model series.
    """
    from cybernetic.cli.theme import t
    return ask(questionary.select(
        "Select Thinking Mode:",
        qmark=QMARK,
        choices=[
            questionary.Choice("Enable Thinking (recommended)", "high"),
            questionary.Choice("Minimal/Disable Thinking", "minimal"),
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select\n- Press ESC to go back",
        style=questionary.Style([
            ("selected", t("menu_selected")),
            ("highlighted", t("menu_highlighted")),
            ("pointer", t("menu_pointer")),
        ]),
    ))


TEMP_LABELS = {
    0.3: "By the Book",
    0.5: "Balanced",
    0.7: "Creative",
    0.9: "Spicy Takes",
    1.2: "Full Degen",
}


def display_agent_config(cfg: dict) -> None:
    """Display an agent config dict as a Rich table."""
    from cybernetic.cli.theme import t
    table = Table(title="Agent Config", box=box.ROUNDED, border_style=t("secondary"))
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("Name", cfg.get("name", ""))
    table.add_row("Ticker", cfg.get("ticker", ""))
    table.add_row("Direction", cfg.get("direction_bias", "bullish"))
    table.add_row("Description", cfg.get("description", "")[:80])
    table.add_row("Tools", ", ".join(cfg.get("tools", [])))
    table.add_row("Target Days", str(cfg.get("target_days", 7)))
    table.add_row("Max Positions", str(cfg.get("max_positions", 5)))
    table.add_row("Personality", cfg.get("personality", "")[:60])

    temp = cfg.get("analysis_temperature", 0.7)
    temp_label = TEMP_LABELS.get(temp, f"{temp}")
    table.add_row("Analysis Temp", f"{temp} ({temp_label})")

    prompt_preview = cfg.get("analysis_system_prompt", "")[:100]
    if len(cfg.get("analysis_system_prompt", "")) > 100:
        prompt_preview += "..."
    table.add_row("System Prompt", prompt_preview)

    console.print(table)
