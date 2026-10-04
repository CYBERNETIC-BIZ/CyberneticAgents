"""Outcome shared by every decision provider."""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ProviderOutcome:
    """One provider's result for a single request."""

    provider: str
    model: Optional[str] = None
    answers: Optional[Dict[str, Any]] = None
    skipped: Optional[str] = None
    error: Optional[str] = None
