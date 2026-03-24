"""CyberneticAgents CLI - Main entry point."""
import time
import random
import typer
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.align import Align
from rich.text import Text
from rich.live import Live
from rich import box
from dotenv import load_dotenv, find_dotenv

# Load .env: try project root first (editable install), then search upward (cwd)
_project_env = Path(__file__).parent.parent.parent / ".env"
if _project_env.exists():
    load_dotenv(_project_env)
else:
    load_dotenv(find_dotenv())

from cybernetic.storage.db import init_db

console = Console()
app = typer.Typer(
    name="cybernetic.biz",
    help="CyberneticAgents: Building Unique Intelligence",
    add_completion=True,
)


GLITCH_CHARS = "█▓▒░╔╗╚╝║═╬╦╩╠╣▀▄▌▐◤◥◣◢"


def _scramble_line(target: str, resolve_ratio: float) -> str:
    """Scramble a line of text, progressively resolving to the target."""
    result = []
    for ch in target:
        if ch == " " or random.random() < resolve_ratio:
            result.append(ch)
        else:
            result.append(random.choice(GLITCH_CHARS))
    return "".join(result)


def _fit_art_to_width(lines: list[str], width: int) -> list[str]:
    """Scale ASCII art lines to fit the terminal width.

    If the art is wider than the terminal, each line is trimmed from the right.
    Trailing whitespace is stripped so centering still works cleanly.
    """
    return [line[:width].rstrip() for line in lines]


def show_banner():
    """Display the CyberneticAgents ASCII art banner with matrix decode animation."""
    from cybernetic.cli.theme import t

    # Look inside the package first, then fall back to docs/
    art_path = Path(__file__).parent / "ascii-text-art.txt"
    if not art_path.exists():
        art_path = Path(__file__).parent.parent.parent / "docs" / "ascii-text-art.txt"
    term_width = console.size.width
    banner = t("banner_style")

    console.print()
    console.print()

    if not art_path.exists() or term_width < 40:
        # Very narrow terminal or missing file: plain text fallback
        console.print(Align.center(Text("CYBERNETIC\n   AGENTS", style=banner)))
        console.print()
        console.print(Align.center(Text("Building Unique Intelligence", style=t("banner_subtitle"))))
        console.print()
        console.print()
        return

    raw_lines = art_path.read_text().splitlines()
    # Remove trailing empty lines
    while raw_lines and not raw_lines[-1].strip():
        raw_lines.pop()

    lines = _fit_art_to_width(raw_lines, term_width)
    display = [""] * len(lines)

    try:
        with Live(console=console, refresh_per_second=30, transient=True) as live:
            for row, target in enumerate(lines):
                # Empty spacer lines pass through immediately
                if not target.strip():
                    display[row] = target
                    frame = Text("\n".join(display), style=banner)
                    live.update(Align.center(frame))
                    time.sleep(0.015)
                    continue

                # Progressive decode: 5 steps per line
                for step in range(1, 6):
                    ratio = step / 5
                    display[row] = target if step == 5 else _scramble_line(target, ratio)
                    frame = Text("\n".join(display), style=banner)
                    live.update(Align.center(frame))
                    time.sleep(0.015)

                display[row] = target
                time.sleep(0.025)

            # Phase 2: brief glitch burst — random line flickers after decode
            non_empty = [i for i, l in enumerate(lines) if l.strip()]
            for _ in range(3):
                time.sleep(0.15 + random.random() * 0.2)
                row = random.choice(non_empty)
                display[row] = _scramble_line(lines[row], 0.85)
                frame = Text("\n".join(display), style=banner)
                live.update(Align.center(frame))
                time.sleep(0.1)
                display[row] = lines[row]
                frame = Text("\n".join(display), style=banner)
                live.update(Align.center(frame))
    except Exception:
        # Fallback: if Live fails (e.g. piped output), just print statically
        pass

    # Print final static version so it stays in terminal scrollback
    art = "\n".join(lines)
    console.print(Align.center(Text(art, style=banner)))
    console.print()
    console.print(Align.center(Text("Building Unique Intelligence", style=t("banner_subtitle"))))
    console.print()
    console.print()


def _show_banner_static():
    """Display the banner without animation (for menu redraws)."""
    from cybernetic.cli.theme import t

    # Look inside the package first, then fall back to docs/
    art_path = Path(__file__).parent / "ascii-text-art.txt"
    if not art_path.exists():
        art_path = Path(__file__).parent.parent.parent / "docs" / "ascii-text-art.txt"
    term_width = console.size.width
    banner = t("banner_style")

    console.print()

    if not art_path.exists() or term_width < 40:
        console.print(Align.center(Text("CYBERNETIC\n   AGENTS", style=banner)))
        console.print()
        console.print(Align.center(Text("Building Unique Intelligence", style=t("banner_subtitle"))))
        console.print()
        return

    raw_lines = art_path.read_text().splitlines()
    while raw_lines and not raw_lines[-1].strip():
        raw_lines.pop()

    lines = _fit_art_to_width(raw_lines, term_width)
    art = "\n".join(lines)
    console.print(Align.center(Text(art, style=banner)))
    console.print()
    console.print(Align.center(Text("Building Unique Intelligence", style=t("banner_subtitle"))))
    console.print()


GITHUB_REPO_URL = "https://github.com/CYBERNETIC-BIZ/CyberneticAgents"
GITHUB_RAW_PYPROJECT = "https://raw.githubusercontent.com/CYBERNETIC-BIZ/CyberneticAgents/main/pyproject.toml"
PIP_INSTALL_URL = f"git+{GITHUB_REPO_URL}.git"


def _get_installed_version() -> str:
    """Get the currently installed package version."""
    try:
        from importlib.metadata import version
        return version("cybernetic-agents")
    except Exception:
        return "0.0.0"


def _check_for_update():
    """Check GitHub for a newer version and notify the user."""
    from cybernetic.cli.theme import load_prefs
    prefs = load_prefs()
    if not prefs.get("check_for_updates", False):
        return

    import re
    try:
        import httpx
        resp = httpx.get(GITHUB_RAW_PYPROJECT, timeout=2.0)
        if resp.status_code != 200:
            return
        match = re.search(r'version\s*=\s*"([^"]+)"', resp.text)
        if not match:
            return
        remote_version = match.group(1)
        local_version = _get_installed_version()
        if remote_version != local_version:
            console.print(
                f"  [bold cyan]⬆ Update available:[/bold cyan] "
                f"[green]v{remote_version}[/green] [dim](you have v{local_version})[/dim]  "
                f"[dim]Go to Config > Update[/dim]"
            )
            console.print()
    except Exception:
        pass  # Fail silently — network issues shouldn't block startup


def _do_update():
    """Run pip upgrade from GitHub. Shared by CLI command and config menu."""
    import subprocess
    import sys

    console.print("[bold cyan]Checking for updates...[/bold cyan]")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", PIP_INSTALL_URL],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            if "already satisfied" in result.stdout.lower() or "already up-to-date" in result.stdout.lower():
                console.print("[green]Already on the latest version.[/green]")
            else:
                console.print("[bold green]Updated successfully![/bold green]")
                console.print("[dim]Restart cybernetic.biz to use the new version.[/dim]")
        else:
            console.print(f"[red]Update failed:[/red]\n{result.stderr}")
    except Exception as e:
        console.print(f"[red]Update failed: {e}[/red]")


def _first_run_setup():
    """Check if this is a first run (no LLM keys) and offer guided setup."""
    from cybernetic.cli.config_flow import has_any_llm_key

    if has_any_llm_key():
        return

    import questionary
    from cybernetic.cli.utils import ask, QMARK
    from cybernetic.cli.theme import t

    console.print(Panel(
        "[bold]Welcome to CyberneticAgents![/bold]\n\n"
        "It looks like you haven't configured any API keys yet.\n"
        "You'll need at least [bold green]one LLM provider key[/bold green] "
        "(OpenAI, Anthropic, Google, xAI, or OpenRouter)\n"
        "to use research and agent features.\n\n"
        "[dim]You can still explore the menus without keys.[/dim]",
        title="[bold] First Run Setup [/bold]",
        border_style="bright_green",
        padding=(1, 2),
    ))

    choice = ask(questionary.select(
        "Would you like to configure your API keys now?",
        qmark=QMARK,
        choices=[
            questionary.Choice("  Yes, set up API keys", value="setup"),
            questionary.Choice("  Skip for now", value="skip"),
        ],
        style=questionary.Style([
            ("selected", t("menu_selected")),
            ("highlighted", t("menu_highlighted")),
            ("pointer", t("menu_pointer")),
        ]),
    ))

    if choice == "setup":
        from cybernetic.cli.config_flow import api_keys_menu
        api_keys_menu()
    else:
        console.print(
            "[dim]No problem! You can configure keys anytime via "
            "Config > API Keys in the menu or [bold]cybernetic.biz config[/bold][/dim]"
        )
    console.print()


@app.command()
def analyze():
    """Research a ticker using multi-agent analysis."""
    init_db()
    show_banner()
    from cybernetic.cli.config_flow import require_llm_key
    if not require_llm_key():
        return
    from cybernetic.cli.research_flow import run_analysis
    run_analysis()


@app.command()
def run(
    agent_id: str = typer.Argument(..., help="Agent ID to run"),
    push: bool = typer.Option(True, "--push/--no-push", help="Push prediction to cybernetic.biz"),
):
    """Run an agent for a single prediction."""
    init_db()
    from cybernetic.cli.config_flow import require_llm_key
    if not require_llm_key():
        return
    from cybernetic.agents.runner import run_agent_once
    run_agent_once(agent_id, push_to_cybernetic=push)


@app.command(name="run-all")
def run_all(
    push: bool = typer.Option(True, "--push/--no-push", help="Push predictions to cybernetic.biz"),
):
    """Run all agents for a single prediction each."""
    init_db()
    from cybernetic.cli.config_flow import require_llm_key
    if not require_llm_key():
        return
    from cybernetic.storage.db import list_agents
    from cybernetic.agents.runner import run_agent_once

    agents = list_agents()
    if not agents:
        console.print("[yellow]No agents found.[/yellow]")
        return

    for agent in agents:
        console.print(f"\n[bold cyan]Running agent: {agent.id}[/bold cyan]")
        run_agent_once(agent.id, push_to_cybernetic=push)


@app.command()
def resolve():
    """Resolve pending predictions by checking current prices."""
    init_db()
    from cybernetic.agents.resolver import resolve_all_pending
    resolve_all_pending()


@app.command()
def dashboard():
    """Show the agent dashboard."""
    init_db()
    from cybernetic.cli.dashboard import show_dashboard
    show_dashboard()


@app.command()
def agents():
    """List all agents."""
    init_db()
    from cybernetic.cli.dashboard import show_dashboard
    show_dashboard()


@app.command(name="agent")
def agent_detail(agent_id: str = typer.Argument(..., help="Agent ID to view")):
    """Show detailed view of an agent."""
    init_db()
    from cybernetic.cli.dashboard import show_agent_detail
    show_agent_detail(agent_id)


@app.command()
def schedule(
    agent_id: str = typer.Argument(..., help="Agent ID to schedule"),
    daily: str = typer.Option("09:30", "--daily", help="Time to run daily (HH:MM)"),
):
    """Print a cron line for scheduling an agent."""
    parts = daily.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    cwd = Path.cwd()

    console.print(Panel(
        f"Add this to your crontab (`crontab -e`):\n\n"
        f"[bold]{minute} {hour} * * 1-5 cd {cwd} && cybernetic.biz run {agent_id}[/bold]\n\n"
        f"[dim]This runs {agent_id} at {daily} on weekdays (Mon-Fri)[/dim]",
        title="Cron Schedule",
        border_style="cyan",
    ))


def run_agents_flow():
    """Interactive sub-menu for running and managing agents."""
    import questionary
    from cybernetic.cli.utils import ask, QMARK
    from cybernetic.storage.db import list_agents, delete_agent
    from cybernetic.cli.theme import t

    agents = list_agents()
    if not agents:
        console.print("[yellow]No agents found. Create one first.[/yellow]")
        return

    green_style = questionary.Style([
        ("selected", t("menu_selected")),
        ("highlighted", t("menu_highlighted")),
        ("pointer", t("menu_pointer")),
        ("checkbox-selected", t("menu_checkbox")),
    ])

    choice = ask(questionary.select(
        "Run Agents:",
        qmark=QMARK,
        choices=[
            questionary.Choice("Run All Agents", value="all"),
            questionary.Choice("Select Agents to Run", value="select"),
            questionary.Choice("Delete an Agent", value="delete"),
            questionary.Choice("Back", value="back"),
        ],
        instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
        style=green_style,
    ))

    if choice is None or choice == "back":
        return

    if choice == "all":
        from cybernetic.agents.runner import run_agent_once
        for a in agents:
            console.print(f"\n[bold cyan]Running: {a.id}[/bold cyan]")
            run_agent_once(a.id)

    elif choice == "select":
        selected = ask(questionary.checkbox(
            "Select agents to run:",
            qmark=QMARK,
            choices=[
                questionary.Choice(f"{a.id} ({a.ticker})", value=a.id)
                for a in agents
            ],
            instruction="\n- Press Space to select/unselect\n- Press 'a' to toggle all\n- Press Enter when done",
            validate=lambda x: len(x) > 0 or "Select at least one agent.",
            style=green_style,
        ))
        if not selected:
            return
        from cybernetic.agents.runner import run_agent_once
        for aid in selected:
            console.print(f"\n[bold cyan]Running: {aid}[/bold cyan]")
            run_agent_once(aid)

    elif choice == "delete":
        target = ask(questionary.select(
            "Select agent to delete:",
            qmark=QMARK,
            choices=[
                questionary.Choice(f"{a.id} ({a.ticker})", value=a.id)
                for a in agents
            ] + [questionary.Choice("Back", value="back")],
            instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
            style=questionary.Style([
                ("selected", t("menu_confirm")),
                ("highlighted", t("menu_confirm")),
                ("pointer", t("menu_confirm")),
            ]),
        ))
        if target is None or target == "back":
            return
        confirm = ask(questionary.confirm(
            f"Delete agent '{target}' and all its predictions/trades?",
            qmark=QMARK,
            default=False,
            style=questionary.Style([("answer", t("menu_confirm"))]),
        ))
        if confirm:
            if delete_agent(target):
                console.print(f"[green]Deleted agent '{target}'[/green]")
            else:
                console.print(f"[red]Agent '{target}' not found[/red]")
        else:
            console.print("[dim]Cancelled.[/dim]")


@app.command()
def config():
    """Configure API keys and theme."""
    from cybernetic.cli.config_flow import config_menu
    config_menu()


@app.command()
def update():
    """Update CyberneticAgents to the latest version from GitHub."""
    _do_update()


@app.command()
def reports():
    """Browse previous analysis reports."""
    init_db()
    from cybernetic.cli.reports import browse_reports
    browse_reports()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Interactive menu when no command is given."""
    if ctx.invoked_subcommand is not None:
        return

    init_db()
    show_banner()
    _check_for_update()
    _first_run_setup()

    import questionary
    from cybernetic.cli.utils import ask, QMARK
    from cybernetic.cli.theme import t

    first_loop = True
    while True:
        if not first_loop:
            console.clear()
            _show_banner_static()
        first_loop = False
        choice = ask(questionary.select(
            "What would you like to do?",
            qmark=QMARK,
            choices=[
                questionary.Separator("─── Research ─────────────────"),
                questionary.Choice(" 🔬 Research a Ticker", value="research"),
                questionary.Choice(" 📄 Previous Reports", value="reports"),
                questionary.Separator("─── Agents ───────────────────"),
                questionary.Choice(" 🤖 Create Agent from Prompt", value="create_prompt"),
                questionary.Choice(" 👥 My Agents", value="agents"),
                questionary.Choice(" 📊 Agent Dashboard", value="dashboard"),
                questionary.Choice(" 🚀 Run Agents", value="run_all"),
                questionary.Choice(" 🎯 Resolve Predictions", value="resolve"),
                questionary.Separator("─── Settings ─────────────────"),
                questionary.Choice(" ⚙️  Config", value="config"),
                questionary.Separator("──────────────────────────────"),
                questionary.Choice(" 👋 Exit", value="exit"),
            ],
            instruction="\n- Use arrow keys to navigate\n- Press Enter to select",
            style=questionary.Style([
                ("qmark", t("menu_qmark")),
                ("question", t("menu_question")),
                ("selected", t("menu_selected")),
                ("highlighted", t("menu_highlighted")),
                ("pointer", t("menu_pointer")),
                ("separator", t("menu_separator")),
            ]),
        ))

        if choice is None:
            continue  # ESC → re-show menu, never quit
        if choice == "exit":
            console.print("[dim]Goodbye![/dim]")
            break
        elif choice == "research":
            from cybernetic.cli.config_flow import require_llm_key
            if not require_llm_key():
                continue
            from cybernetic.cli.research_flow import run_analysis
            run_analysis()
        elif choice == "create_prompt":
            from cybernetic.cli.config_flow import require_llm_key
            if not require_llm_key():
                continue
            from cybernetic.cli.create_flow import run_create_from_prompt
            run_create_from_prompt()
        elif choice == "agents":
            from cybernetic.cli.my_agents import my_agents_flow
            my_agents_flow()
        elif choice == "dashboard":
            from cybernetic.cli.dashboard import show_dashboard
            show_dashboard()
            console.input("\n[dim]Press Enter to continue...[/dim]")
        elif choice == "run_all":
            from cybernetic.cli.config_flow import require_llm_key
            if not require_llm_key():
                continue
            run_agents_flow()
            console.input("\n[dim]Press Enter to continue...[/dim]")
        elif choice == "resolve":
            from cybernetic.agents.resolver import resolve_all_pending
            resolve_all_pending()
            console.input("\n[dim]Press Enter to continue...[/dim]")
        elif choice == "reports":
            from cybernetic.cli.reports import browse_reports
            browse_reports()
        elif choice == "config":
            from cybernetic.cli.config_flow import config_menu
            config_menu()


if __name__ == "__main__":
    app()
