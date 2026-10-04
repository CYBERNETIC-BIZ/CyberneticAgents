"""Run the default decision providers on one piece of text."""

from typing import Any, Dict, Optional, Sequence

from cybernetic.decisions.jev import JevProvider
from cybernetic.decisions.laya import LayaProvider
from cybernetic.decisions.questions import DEFAULT_QUESTIONS
from cybernetic.decisions.report import render_report
from cybernetic.decisions.types import ProviderOutcome

DEFAULT_PROVIDER_NAMES = ("Laya", "Jev")


def default_providers() -> list:
    """Laya first, then Jev. Both are always included."""
    return [LayaProvider(), JevProvider()]


def run_decision(
    state: str,
    questions: Optional[Dict[str, Any]] = None,
    providers: Optional[Sequence[Any]] = None,
) -> str:
    """Evaluate ``state`` with every provider and return the labeled report."""
    schema = dict(DEFAULT_QUESTIONS if questions is None else questions)
    selected = list(default_providers() if providers is None else providers)
    outcomes = []
    for provider in selected:
        name = getattr(provider, "name", "provider")
        try:
            outcome = provider.evaluate(state, schema)
        except Exception as exc:
            outcome = ProviderOutcome(provider=str(name), error=f"{name} failed: {exc}")
        outcomes.append(outcome)
    return render_report(state, outcomes)
