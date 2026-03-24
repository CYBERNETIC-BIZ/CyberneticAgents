"""Resolve pending predictions by checking current prices."""
import yfinance as yf
from rich.console import Console
from rich.table import Table
from rich import box

from cybernetic.storage.db import (
    get_pending_predictions, resolve_prediction,
    save_trade, get_agent, update_agent_balance,
    get_trade_for_prediction,
)
from cybernetic.storage.models import Trade

console = Console()

FEE_RATE = 0.001  # 0.1%


def resolve_all_pending():
    """Check all pending predictions past their target date and resolve them."""
    pending = get_pending_predictions()

    if not pending:
        console.print("[cyan]No pending predictions to resolve.[/cyan]")
        return

    console.print(f"[cyan]Resolving {len(pending)} pending predictions...[/cyan]")

    results_table = Table(title="Resolved Predictions", box=box.ROUNDED, border_style="cyan")
    results_table.add_column("Agent")
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

            # Look up the opening trade to get exact quantity
            open_side = "SHORT_SELL" if pred.direction == "BEARISH" else "BUY"
            open_trade = get_trade_for_prediction(pred.id, open_side)

            if not open_trade:
                continue

            quantity = open_trade.quantity

            if pred.direction == "BEARISH":
                # Short cover: effective price = 2 * entry - exit
                # This represents getting back collateral + profit (or - loss)
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

            # Display P&L
            if pred.direction == "BEARISH":
                pnl_pct = ((pred.entry_price - exit_price) / pred.entry_price) * 100
            else:
                pnl_pct = ((exit_price - pred.entry_price) / pred.entry_price) * 100

            result_color = "green" if result == "correct" else "red"

            results_table.add_row(
                pred.agent_id,
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
