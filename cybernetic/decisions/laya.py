"""Laya decision provider.

The package and its checkpoints are optional at runtime. CI does not download
them. Tests pass a fixture file instead of loading a model.
"""

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from cybernetic.decisions.report import answers_from_payload
from cybernetic.decisions.types import ProviderOutcome
from cybernetic.spend import (
    JEV_TOKEN_OVERHEAD,
    estimate_text_tokens,
    get_guard,
    live_calls_blocked_reason,
)

FIXTURE_ENV = "CYBERNETIC_LAYA_FIXTURE"

SKIP_MISSING = (
    "Laya live call skipped: the laya package is not installed. "
    "Install the optional extra with pip install 'cybernetic-agents[laya]'. "
    "No checkpoint was loaded and no network call was made."
)

Predict = Callable[[str, Dict[str, Any]], Dict[str, Any]]


def _load_router() -> Any:
    # Optional extra: importing laya pulls in torch. CI does not install it,
    # so the import stays inside the live path rather than at module import.
    import laya

    return laya.Router()


class LayaProvider:
    """Default local System One provider."""

    name = "Laya"

    def __init__(self, predict: Optional[Predict] = None) -> None:
        self._predict = predict

    def evaluate(self, state: str, questions: Dict[str, Any]) -> ProviderOutcome:
        fixture = os.environ.get(FIXTURE_ENV, "").strip()
        if self._predict is not None:
            return self._from_call(self._predict, state, questions)
        if fixture:
            return self._from_fixture(Path(fixture))
        blocked = live_calls_blocked_reason()
        if blocked is not None:
            return ProviderOutcome(provider=self.name, skipped=blocked)
        try:
            router = _load_router()
        except ImportError:
            return ProviderOutcome(provider=self.name, skipped=SKIP_MISSING)
        except Exception as exc:
            return ProviderOutcome(provider=self.name, error=f"Laya failed to load: {exc}")

        encoded = json.dumps({"state": state, "questions": questions}, default=str)
        decision = get_guard().authorize(
            provider="laya",
            model="laya",
            input_tokens=estimate_text_tokens(encoded, overhead=JEV_TOKEN_OVERHEAD),
            output_tokens=0,
        )
        if not decision.allowed:
            return ProviderOutcome(provider=self.name, skipped=decision.reason)

        def _predict(text: str, schema: Dict[str, Any]) -> Dict[str, Any]:
            result = router.predict(text, schema)
            if not isinstance(result, dict):
                raise TypeError("Laya predict did not return an object")
            return result

        return self._from_call(_predict, state, questions)

    def _from_fixture(self, path: Path) -> ProviderOutcome:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return ProviderOutcome(provider=self.name, error=f"Laya fixture unreadable: {exc}")
        if not isinstance(payload, dict):
            return ProviderOutcome(provider=self.name, error="Laya fixture must be a JSON object")
        return self._from_payload(payload)

    def _from_call(
        self,
        predict: Predict,
        state: str,
        questions: Dict[str, Any],
    ) -> ProviderOutcome:
        try:
            payload = predict(state, questions)
        except Exception as exc:
            return ProviderOutcome(provider=self.name, error=f"Laya failed: {exc}")
        return self._from_payload(payload)

    def _from_payload(self, payload: Dict[str, Any]) -> ProviderOutcome:
        model, answers = answers_from_payload(payload)
        if answers is None:
            return ProviderOutcome(
                provider=self.name,
                model=model,
                error="Laya response did not include answers",
            )
        return ProviderOutcome(provider=self.name, model=model, answers=answers)
