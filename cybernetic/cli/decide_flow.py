"""CLI flow that shows Laya and Jev for the same text."""

from pathlib import Path
from typing import Optional

import questionary
import typer
from rich.console import Console

from cybernetic.cli.theme import t
from cybernetic.cli.utils import QMARK, ask
from cybernetic.decisions.questions import load_questions
from cybernetic.decisions.runner import run_decision

console = Console()


def execute_decide(text: str, questions_path: Optional[Path] = None) -> str:
    """Evaluate ``text`` with the default providers and print the report.

    Raises:
        typer.Exit: The questions file is invalid or the text is empty.
    """
    cleaned = text.strip()
    if not cleaned:
        console.print("[red]Enter some text to evaluate.[/red]")
        raise typer.Exit(1)
    questions = None
    if questions_path is not None:
        try:
            questions = load_questions(questions_path)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
    report = run_decision(cleaned, questions)
    console.print(report, highlight=False)
    return report


def prompt_and_decide() -> None:
    """Ask for text, then show Laya and Jev. Esc returns to the menu."""
    text = ask(questionary.text(
        "Text for Laya and Jev to evaluate:",
        qmark=QMARK,
        style=questionary.Style([
            ("text", t("menu_text")),
            ("highlighted", "noinherit"),
        ]),
    ))
    if text is None or not str(text).strip():
        return
    execute_decide(str(text))
