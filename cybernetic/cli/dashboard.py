"""Agent dashboard with Rich terminal UI."""
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.align import Align

from cybernetic.storage.db import list_agents, get_agent_stats, get_agent_predictions, get_open_position_cost

console = Console()


def show_dashboard():
    """Display the agent dashboard with all agents and their stats."""
    from cybernetic.cli.theme import t
    agents = list_agents()

    if not agents:
        console.print("[yellow]No agents found. Research a ticker first to generate an agent.[/yellow]")
        return

    table = Table(
        title="Agent Dashboard",
        box=box.ROUNDED,
        border_style=t("secondary"),
        show_lines=True,
    )
    table.add_column("Agent", style=f"bold {t('primary')}")
    table.add_column("Ticker", style=t("secondary"), justify="center")
    table.add_column("Accuracy", justify="center")
    table.add_column("Portfolio", justify="right")
    table.add_column("Predictions", justify="center")
    table.add_column("Pending", justify="center")

    for agent in agents:
        stats = get_agent_stats(agent.id)
        accuracy_str = f"{stats['accuracy']:.0f}% ({stats['correct']}/{stats['resolved']})" if stats['resolved'] > 0 else "N/A"
        open_cost = get_open_position_cost(agent.id)
        total_value = agent.portfolio_balance + open_cost
        pnl = total_value - 10000
        pnl_color = "green" if pnl >= 0 else "red"
        portfolio_str = f"[{pnl_color}]${total_value:,.2f} ({pnl:+,.2f})[/{pnl_color}]"

        table.add_row(
            agent.id,
            agent.ticker,
            accuracy_str,
            portfolio_str,
            str(stats["total"]),
            str(stats["pending"]),
        )

    console.print(table)


def show_agent_detail(agent_id: str):
    """Show detailed view of a specific agent."""
    from cybernetic.storage.db import get_agent
    agent = get_agent(agent_id)
    if not agent:
        console.print(f"[red]Agent '{agent_id}' not found.[/red]")
        return

    stats = get_agent_stats(agent_id)
    predictions = get_agent_predictions(agent_id)

    # Agent info panel
    open_cost = get_open_position_cost(agent_id)
    total_value = agent.portfolio_balance + open_cost
    pnl = total_value - 10000
    pnl_color = "green" if pnl >= 0 else "red"

    info = f"""[bold]{agent.name}[/bold]
Ticker: {agent.ticker}
Portfolio: [{pnl_color}]${total_value:,.2f} ({pnl:+,.2f})[/{pnl_color}]
Accuracy: {stats['accuracy']:.0f}% ({stats['correct']}/{stats['resolved']})
Total Predictions: {stats['total']}
Pending: {stats['pending']}
Created: {agent.created_at}"""

    from cybernetic.cli.theme import t
    console.print(Panel(info, title=f"Agent: {agent.id}", border_style=t("secondary")))

    # Predictions table
    if predictions:
        pred_table = Table(title="Recent Predictions", box=box.ROUNDED, border_style=t("border_messages"))
        pred_table.add_column("#", style="dim")
        pred_table.add_column("Ticker")
        pred_table.add_column("Direction")
        pred_table.add_column("Confidence")
        pred_table.add_column("Entry")
        pred_table.add_column("Exit")
        pred_table.add_column("Result")
        pred_table.add_column("Date")

        for pred in predictions[:20]:
            dir_color = "green" if pred.direction == "BULLISH" else "red"
            result_str = ""
            if pred.result in ("correct", "CORRECT"):
                result_str = "[green]CORRECT[/green]"
            elif pred.result in ("incorrect", "INCORRECT"):
                result_str = "[red]INCORRECT[/red]"
            else:
                result_str = "[yellow]Pending[/yellow]"

            exit_str = f"${pred.exit_price:.2f}" if pred.exit_price else "-"

            pred_table.add_row(
                str(pred.id),
                pred.ticker,
                f"[{dir_color}]{pred.direction}[/{dir_color}]",
                f"{pred.confidence:.0%}",
                f"${pred.entry_price:.2f}",
                exit_str,
                result_str,
                str(pred.created_at)[:10] if pred.created_at else "",
            )

        console.print(pred_table)
