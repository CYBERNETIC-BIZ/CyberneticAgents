"""Jev decision provider.

Jev is TypeSafe's hosted System One model (``jev-latest``) at
``POST /v1/systemone``. The CLI did not ship a Jev client; this module is
that client. A missing ``TYPESAFE_API_KEY`` skips the call. No key is stored
in the repo.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from cybernetic.decisions.report import answers_from_payload
from cybernetic.decisions.types import ProviderOutcome
from cybernetic.spend import JEV_TOKEN_OVERHEAD, estimate_text_tokens, get_guard, live_calls_blocked_reason

FIXTURE_ENV = "CYBERNETIC_JEV_FIXTURE"
API_KEY_ENV = "TYPESAFE_API_KEY"
BASE_URL_ENV = "TYPESAFE_BASE_URL"
MODEL_ENV = "TYPESAFE_DEFAULT_MODEL"
DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"

SKIP_KEY = (
    "Jev live call skipped: TYPESAFE_API_KEY is not set. "
    "No request was sent to api.typesafe.ai."
)


class JevProvider:
    """Default hosted System One provider (``jev-latest``)."""

    name = "Jev"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self._transport = transport

    def evaluate(self, state: str, questions: Dict[str, Any]) -> ProviderOutcome:
        fixture = os.environ.get(FIXTURE_ENV, "").strip()
        # A fixture stands in for the network unless a test injected a transport.
        if fixture and self._transport is None:
            return self._from_fixture(Path(fixture))
        blocked = live_calls_blocked_reason()
        if blocked is not None:
            return ProviderOutcome(provider=self.name, skipped=blocked)
        api_key = self._api_key
        if api_key is None:
            api_key = os.environ.get(API_KEY_ENV, "")
        if not api_key.strip():
            return ProviderOutcome(provider=self.name, skipped=SKIP_KEY)
        base_url = self._base_url or os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL
        model = self._model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL
        encoded = json.dumps({"state": state, "questions": questions}, default=str)
        decision = get_guard().authorize(
            provider="jev",
            model=model,
            input_tokens=estimate_text_tokens(encoded, overhead=JEV_TOKEN_OVERHEAD),
            output_tokens=0,
        )
        if not decision.allowed:
            return ProviderOutcome(provider=self.name, skipped=decision.reason)
        return self._post(state, questions, api_key.strip(), base_url.rstrip("/"), model)

    def _from_fixture(self, path: Path) -> ProviderOutcome:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return ProviderOutcome(provider=self.name, error=f"Jev fixture unreadable: {exc}")
        if not isinstance(payload, dict):
            return ProviderOutcome(provider=self.name, error="Jev fixture must be a JSON object")
        return self._from_payload(payload)

    def _post(
        self,
        state: str,
        questions: Dict[str, Any],
        api_key: str,
        base_url: str,
        model: str,
    ) -> ProviderOutcome:
        url = f"{base_url}/v1/systemone"
        body = {"state": state, "model": model, "questions": questions}
        try:
            with httpx.Client(transport=self._transport, timeout=30.0) as client:
                response = client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        except httpx.HTTPError as exc:
            return ProviderOutcome(provider=self.name, error=f"Jev request failed: {exc}")
        if response.status_code >= 400:
            detail = response.text.strip().replace("\n", " ")[:240]
            return ProviderOutcome(
                provider=self.name,
                error=f"Jev returned HTTP {response.status_code}: {detail}",
            )
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return ProviderOutcome(provider=self.name, error="Jev returned a response that was not JSON")
        if not isinstance(payload, dict):
            return ProviderOutcome(provider=self.name, error="Jev response was not a JSON object")
        return self._from_payload(payload)

    def _from_payload(self, payload: Dict[str, Any]) -> ProviderOutcome:
        model, answers = answers_from_payload(payload)
        if answers is None:
            return ProviderOutcome(
                provider=self.name,
                model=model,
                error="Jev response did not include answers",
            )
        return ProviderOutcome(provider=self.name, model=model or DEFAULT_MODEL, answers=answers)
