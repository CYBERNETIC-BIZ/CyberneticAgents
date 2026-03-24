"""API key configuration flow."""
import os
from pathlib import Path

import questionary
from dotenv import dotenv_values, find_dotenv, set_key
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from cybernetic.cli.utils import ask, QMARK

console = Console()

# LLM provider keys (at least one needed for core features)
LLM_KEYS = [
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "OPENROUTER_API_KEY",
]

# API keys that can be configured (order matches .env.example)
API_KEYS = [
    ("OPENAI_API_KEY", "OpenAI"),
    ("GOOGLE_API_KEY", "Google Gemini"),
    ("ANTHROPIC_API_KEY", "Anthropic Claude"),
    ("XAI_API_KEY", "xAI Grok"),
    ("OPENROUTER_API_KEY", "OpenRouter"),
    ("ALPHA_VANTAGE_API_KEY", "Alpha Vantage"),
]


def has_any_llm_key() -> bool:
    """Check if at least one LLM API key is configured."""
    env_path = find_dotenv()
    file_values = dotenv_values(env_path) if env_path else {}
    for key in LLM_KEYS:
        if file_values.get(key, "") or os.environ.get(key, ""):
            return True
    return False


def require_llm_key() -> bool:
    """Check for LLM keys and show error if none configured. Returns True if OK."""
    if has_any_llm_key():
        return True
    console.print()
    console.print(Panel(
        "[bold red]No LLM API key configured.[/bold red]\n\n"
        "This feature requires at least one AI provider key.\n"
        "Go to [bold green]Config > API Keys[/bold green] in the main menu "
        "or run:\n\n"
        "  [bold]cybernetic.biz config[/bold]\n\n"
        "Supported providers: OpenAI, Anthropic, Google Gemini, xAI, OpenRouter",
        title="[bold] API Key Required [/bold]",
        border_style="red",
        padding=(1, 2),
    ))
    console.print()
    return False


def _get_dotenv_path() -> str:
    """Get path to .env file, creating it if it doesn't exist."""
    path = find_dotenv()
    if not path:
        # Create .env in project root (same dir as pyproject.toml)
        root = Path(__file__).parent.parent.parent
        path = str(root / ".env")
        Path(path).touch()
    return path


def _mask_key(value: str) -> str:
    """Mask an API key, showing first 2 and last 4 chars."""
    if len(value) <= 8:
        return value[:1] + "..." + value[-2:]
    return value[:2] + "..." + value[-4:]


def _build_status_lines(env_path: str) -> list[tuple[str, str, bool]]:
    """Build list of (env_var, display_status, is_set) tuples."""
    file_values = dotenv_values(env_path)
    lines = []
    for env_var, label in API_KEYS:
        # Check both .env file and current os.environ
        value = file_values.get(env_var, "") or os.environ.get(env_var, "")
        if value:
            lines.append((env_var, f"{label}: {_mask_key(value)}", True))
        else:
            lines.append((env_var, f"{label}: not set", False))
    return lines


def _menu_style():
    """Build questionary style from current theme."""
    from cybernetic.cli.theme import t
    return questionary.Style([
        ("qmark", t("menu_qmark")),
        ("question", t("menu_question")),
        ("selected", t("menu_selected")),
        ("highlighted", t("menu_highlighted")),
        ("pointer", t("menu_pointer")),
    ])


def config_menu():
    """Top-level config menu: API Keys, LLM Settings, Theme, Updates."""
    while True:
        from cybernetic.cli.theme import load_prefs
        prefs = load_prefs()
        update_check_enabled = prefs.get("check_for_updates", False)
        update_check_label = "on" if update_check_enabled else "off"

        style = _menu_style()
        choice = ask(questionary.select(
            "Config:",
            qmark=QMARK,
            choices=[
                questionary.Choice("  API Keys", value="api_keys"),
                questionary.Choice("  LLM Settings", value="llm"),
                questionary.Choice("  Theme", value="theme"),
                questionary.Separator("──────────────────────────────"),
                questionary.Choice("  Update Now", value="update"),
                questionary.Choice(f"  Check for Updates on Startup ({update_check_label})", value="toggle_updates"),
                questionary.Separator("──────────────────────────────"),
                questionary.Choice("  Back", value="back"),
            ],
            instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
            style=style,
        ))

        if choice is None or choice == "back":
            return
        elif choice == "api_keys":
            api_keys_menu()
        elif choice == "llm":
            llm_settings_menu()
        elif choice == "theme":
            theme_menu()
        elif choice == "update":
            from cybernetic.cli.app import _do_update
            _do_update()
            console.input("\n[dim]Press Enter to continue...[/dim]")
        elif choice == "toggle_updates":
            from cybernetic.cli.theme import save_prefs
            prefs["check_for_updates"] = not update_check_enabled
            save_prefs(prefs)
            new_state = "enabled" if prefs["check_for_updates"] else "disabled"
            console.print(f"[green]  Check for updates on startup: {new_state}[/green]")


def llm_settings_menu():
    """Configure the global LLM provider and models used for agent runs."""
    from cybernetic.config import get_config, set_config
    from cybernetic.cli.utils import select_llm_provider, select_shallow_thinking_agent, select_deep_thinking_agent
    from cybernetic.cli.theme import t

    config = get_config()
    style = _menu_style()

    while True:
        # Show current settings
        current_provider = config.get("llm_provider", "openai").capitalize()
        current_quick = config.get("quick_think_llm", "gpt-5-mini")
        current_deep = config.get("deep_think_llm", "gpt-5.2")

        status_text = Text()
        status_text.append("  Provider:      ", style="bold")
        status_text.append(f"{current_provider}\n")
        status_text.append("  Quick-Think:   ", style="bold")
        status_text.append(f"{current_quick}\n")
        status_text.append("  Deep-Think:    ", style="bold")
        status_text.append(f"{current_deep}\n")

        console.print()
        console.print(Panel(
            status_text,
            title="[bold]Global LLM Settings[/bold]",
            border_style=t("border_config"),
            padding=(1, 2),
        ))

        choice = ask(questionary.select(
            "What to configure?",
            qmark=QMARK,
            choices=[
                questionary.Choice("  Change Provider & Models", value="provider"),
                questionary.Choice("  Change Quick-Think Model Only", value="quick"),
                questionary.Choice("  Change Deep-Think Model Only", value="deep"),
                questionary.Choice("  Back", value="back"),
            ],
            instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
            style=style,
        ))

        if choice is None or choice == "back":
            return

        if choice == "provider":
            result = select_llm_provider()
            if result is None:
                continue
            provider_name, base_url = result
            config["llm_provider"] = provider_name.lower()
            config["backend_url"] = base_url
            set_config(config)

            # Select both models for the new provider
            quick = select_shallow_thinking_agent(provider_name.lower())
            if quick:
                config["quick_think_llm"] = quick
                set_config(config)

            deep = select_deep_thinking_agent(provider_name.lower())
            if deep:
                config["deep_think_llm"] = deep
                set_config(config)

            console.print(f"[green]  LLM settings updated: {provider_name}[/green]")

        elif choice == "quick":
            provider = config.get("llm_provider", "openai").lower()
            quick = select_shallow_thinking_agent(provider)
            if quick:
                config["quick_think_llm"] = quick
                set_config(config)
                console.print(f"[green]  Quick-Think model set to: {quick}[/green]")

        elif choice == "deep":
            provider = config.get("llm_provider", "openai").lower()
            deep = select_deep_thinking_agent(provider)
            if deep:
                config["deep_think_llm"] = deep
                set_config(config)
                console.print(f"[green]  Deep-Think model set to: {deep}[/green]")


def theme_menu():
    """Theme selection menu."""
    from cybernetic.cli.theme import THEMES, get_theme_name, set_theme, t

    current = get_theme_name()
    style = _menu_style()

    choices = []
    for key, theme in THEMES.items():
        marker = " *" if key == current else "  "
        choices.append(questionary.Choice(
            f" {marker} {theme['name']} - {theme['description']}",
            value=key,
        ))
    choices.append(questionary.Choice("   Back", value="back"))

    selected = ask(questionary.select(
        f"Select Theme (current: {THEMES[current]['name']}):",
        qmark=QMARK,
        choices=choices,
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
        style=style,
    ))

    if selected is None or selected == "back":
        return

    set_theme(selected)
    console.print(f"[green]  Theme set to: {THEMES[selected]['name']}[/green]")


def api_keys_menu():
    """Interactive API key configuration menu."""
    from cybernetic.cli.theme import t
    green_style = _menu_style()

    env_path = _get_dotenv_path()

    while True:
        # Build status panel
        status = _build_status_lines(env_path)
        text = Text()
        for _env_var, display, is_set in status:
            icon = "  ✅  " if is_set else "  ❌  "
            style = "green" if is_set else "red"
            text.append(icon, style=style)
            text.append(display + "\n", style=style if not is_set else "")

        # Ollama status (no key needed)
        from cybernetic.llm.ollama import is_ollama_installed, is_ollama_running, list_models
        if is_ollama_installed():
            if is_ollama_running():
                models = list_models()
                model_names = ", ".join(m["name"] for m in models) if models else "no models pulled"
                text.append(f"  ✅  Ollama (local): running — {model_names}\n", style="green")
            else:
                text.append("  ⚠️  Ollama (local): installed but not running\n", style="yellow")
        else:
            text.append("  ─   Ollama (local): not installed — https://ollama.com\n", style="dim")

        console.print()
        console.print(Panel(
            text,
            title="[bold]API Key Configuration[/bold]",
            border_style=t("border_config"),
            padding=(1, 2),
        ))

        # Build choices
        choices = []
        for env_var, label in API_KEYS:
            choices.append(questionary.Choice(f"  Set {label}", value=env_var))
        choices.append(questionary.Choice("  Back", value="back"))

        selected = ask(questionary.select(
            "Select a key to configure:",
            qmark=QMARK,
            choices=choices,
            instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
            style=green_style,
        ))

        if selected is None or selected == "back":
            return

        # Prompt for new value (masked input)
        new_value = ask(questionary.password(
            f"Enter value for {selected}:",
            qmark=QMARK,
            style=green_style,
        ))

        if new_value is None or new_value.strip() == "":
            console.print("[dim]Skipped (no value entered).[/dim]")
            continue

        new_value = new_value.strip()

        # Write to .env file
        set_key(env_path, selected, new_value)

        # Update current process environment so it takes effect immediately
        os.environ[selected] = new_value

        label = dict(API_KEYS)[selected]
        console.print(f"[green]  ✅ {label} updated successfully.[/green]")
