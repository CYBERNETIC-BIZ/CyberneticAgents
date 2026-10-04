"""Hard spend guard for automated model calls.

Assumptions, checked against published rates on 2026-10-04:

* Cheap OpenAI model for any test that needs a live model: ``gpt-5-nano``.
  OpenAI lists it at $0.05 / 1M input tokens and $0.40 / 1M output tokens
  (https://developers.openai.com/api/docs/models/gpt-5-nano).
* Jev (TypeSafe ``jev-latest``) input is $0.042 / 1M tokens and output is $0,
  the published System One rate. Token estimate is ``len(text) // 4`` plus
  512 overhead tokens. Measured Jev overhead is about 260; 512 is the
  reservation used here so the estimate does not come in low.
* Laya runs locally, so a live Laya forward pass is €0. It still counts as
  one live run.
* FX: 1 USD is counted as 1 EUR. That does not loosen the cap while one
  dollar buys one euro or less. Revisit the fraction if the dollar buys
  more than one euro.

Caps:

* ``PER_RUN_CAP_EUR`` (€1) is the most one process may reserve. It is well
  under the owner's €20 monthly ceiling.
* ``MONTHLY_CAP_EUR`` (€20) is the owner's ceiling for this repo's automated
  API calls.
* ``LIVE_RUN_PAUSE`` (10) stops the next live run until
  ``CYBERNETIC_SPEND_CONTINUE`` equals that run count. The same value does
  not unlock the following batch.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Literal, Optional

from typing_extensions import Never

CHEAP_OPENAI_MODEL = "gpt-5-nano"
OPENAI_INPUT_USD_PER_MILLION = 0.05
OPENAI_OUTPUT_USD_PER_MILLION = 0.40
JEV_INPUT_USD_PER_MILLION = 0.042
JEV_OUTPUT_USD_PER_MILLION = 0.0
# micro-USD charged for one million tokens. 1 USD = 1_000_000 micro-USD.
OPENAI_INPUT_MICROUSD_PER_MILLION = 50_000
OPENAI_OUTPUT_MICROUSD_PER_MILLION = 400_000
JEV_INPUT_MICROUSD_PER_MILLION = 42_000
JEV_OUTPUT_MICROUSD_PER_MILLION = 0
# 1 USD = 1 EUR. Numerator / denominator converts micro-USD to micro-EUR.
USD_TO_EUR_NUM = 1
USD_TO_EUR_DEN = 1

MONTHLY_CAP_EUR = 20.0
PER_RUN_CAP_EUR = 1.0
LIVE_RUN_PAUSE = 10
JEV_TOKEN_OVERHEAD = 512

MONTHLY_CAP_MICRO_EUR = 20_000_000
PER_RUN_CAP_MICRO_EUR = 1_000_000

LEDGER_ENV = "CYBERNETIC_SPEND_LEDGER"
LIVE_CALLS_ENV = "CYBERNETIC_LIVE_CALLS"
CONTINUE_ENV = "CYBERNETIC_SPEND_CONTINUE"
SKIP_ENV = "CYBERNETIC_SKIP_LIVE_DECISIONS"

ProviderKind = Literal["openai", "jev", "laya"]

SKIP_CI = "Live call skipped in CI. No API request was sent."
SKIP_OPT_IN = (
    "Live call skipped: set CYBERNETIC_LIVE_CALLS=1 to opt in. "
    "No API request was sent."
)
SKIP_FORCED = (
    "Live call skipped: CYBERNETIC_SKIP_LIVE_DECISIONS=1. "
    "No API request was sent."
)


@dataclass(frozen=True)
class SpendDecision:
    """Whether one live call may be sent."""

    allowed: bool
    reason: str
    estimated_eur: float


def _never(value: Never) -> None:
    raise AssertionError(f"unhandled provider: {value}")


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def ci_blocks_live_calls() -> bool:
    """GitHub Actions sets CI=true. Any of these values blocks live calls."""
    return os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


def live_calls_blocked_reason() -> Optional[str]:
    """Return a skip reason when a live call must not leave this process."""
    if os.environ.get(SKIP_ENV) == "1":
        return SKIP_FORCED
    if ci_blocks_live_calls():
        return SKIP_CI
    if os.environ.get(LIVE_CALLS_ENV) != "1":
        return SKIP_OPT_IN
    return None


def estimate_text_tokens(text: str, *, overhead: int = 0) -> int:
    """Conservative token count from character length."""
    return max(1, len(text) // 4) + overhead


def micro_eur_for(provider: ProviderKind, input_tokens: int, output_tokens: int) -> int:
    """Reserved euro cost in millionths of a euro."""
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("token counts must be non-negative")
    if provider == "openai":
        micro_usd = (
            input_tokens * OPENAI_INPUT_MICROUSD_PER_MILLION
            + output_tokens * OPENAI_OUTPUT_MICROUSD_PER_MILLION
        ) // 1_000_000
    elif provider == "jev":
        micro_usd = (
            input_tokens * JEV_INPUT_MICROUSD_PER_MILLION
            + output_tokens * JEV_OUTPUT_MICROUSD_PER_MILLION
        ) // 1_000_000
    elif provider == "laya":
        micro_usd = 0
    else:
        _never(provider)
    return micro_usd * USD_TO_EUR_NUM // USD_TO_EUR_DEN


def eur_from_micro(micro: int) -> float:
    return micro / 1_000_000


def default_ledger_path() -> Path:
    override = os.environ.get(LEDGER_ENV, "").strip()
    if override:
        return Path(override)
    return Path(".cybernetic") / "spend-ledger.json"


def _pause_reason(live_runs: int) -> str:
    return (
        f"Live run pause: {live_runs} live runs completed "
        f"(stop every {LIVE_RUN_PAUSE}). "
        f"Set {CONTINUE_ENV}={live_runs} to allow the next {LIVE_RUN_PAUSE}. "
        "Do not loop on an API."
    )


def _continue_value() -> Optional[int]:
    raw = os.environ.get(CONTINUE_ENV, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


class SpendGuard:
    """Monthly ledger plus an in-process per-run total."""

    def __init__(
        self,
        path: Path,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.path = path
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._run_micro = 0

    def authorize(
        self,
        *,
        provider: ProviderKind,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> SpendDecision:
        """Reserve one live call, or refuse it before any request is sent."""
        blocked = live_calls_blocked_reason()
        if blocked is not None:
            return SpendDecision(False, blocked, 0.0)
        if provider == "openai" and model != CHEAP_OPENAI_MODEL:
            return SpendDecision(
                False,
                (
                    "Live OpenAI calls must use the cheap model "
                    f"{CHEAP_OPENAI_MODEL}. Refusing {model or 'an empty model'}."
                ),
                0.0,
            )
        estimate = micro_eur_for(provider, input_tokens, output_tokens)
        state = self._load()
        self._roll_month(state)
        live_runs = int(state["live_runs"])
        acknowledged = int(state["acknowledged_pause"])
        if live_runs > 0 and live_runs % LIVE_RUN_PAUSE == 0 and acknowledged < live_runs:
            continuation = _continue_value()
            if continuation != live_runs:
                return SpendDecision(False, _pause_reason(live_runs), eur_from_micro(estimate))
            state["acknowledged_pause"] = live_runs
        month_micro = int(state["month_micro_eur"])
        if month_micro + estimate > MONTHLY_CAP_MICRO_EUR:
            return SpendDecision(
                False,
                (
                    "Monthly spend cap: this call is estimated at "
                    f"€{eur_from_micro(estimate):.6f} and would bring the month to "
                    f"€{eur_from_micro(month_micro + estimate):.6f}, "
                    f"above €{MONTHLY_CAP_EUR:.0f}."
                ),
                eur_from_micro(estimate),
            )
        if self._run_micro + estimate > PER_RUN_CAP_MICRO_EUR:
            return SpendDecision(
                False,
                (
                    "Per-run spend cap: this call is estimated at "
                    f"€{eur_from_micro(estimate):.6f} and would bring the run to "
                    f"€{eur_from_micro(self._run_micro + estimate):.6f}, "
                    f"above €{PER_RUN_CAP_EUR:.0f}."
                ),
                eur_from_micro(estimate),
            )
        state["live_runs"] = live_runs + 1
        state["month_micro_eur"] = month_micro + estimate
        self._run_micro += estimate
        self._save(state)
        return SpendDecision(True, "allowed", eur_from_micro(estimate))

    def _month_key(self) -> str:
        current = self._clock()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc).strftime("%Y-%m")

    def _empty(self) -> Dict[str, object]:
        return {
            "month": self._month_key(),
            "month_micro_eur": 0,
            "live_runs": 0,
            "acknowledged_pause": 0,
        }

    def _roll_month(self, state: Dict[str, object]) -> None:
        if state.get("month") != self._month_key():
            state.clear()
            state.update(self._empty())

    def _load(self) -> Dict[str, object]:
        if not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        if not isinstance(data, dict):
            return self._empty()
        merged = self._empty()
        merged.update(data)
        return merged

    def _save(self, state: Dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)


_GUARDS: Dict[str, SpendGuard] = {}


def get_guard() -> SpendGuard:
    """Return the process guard for the configured ledger path."""
    path = default_ledger_path()
    key = str(path.resolve()) if path.is_absolute() else str(path)
    guard = _GUARDS.get(key)
    if guard is None:
        guard = SpendGuard(path)
        _GUARDS[key] = guard
    return guard


def reset_guard_cache() -> None:
    """Drop cached guards. Tests use this after pointing the ledger elsewhere."""
    _GUARDS.clear()
