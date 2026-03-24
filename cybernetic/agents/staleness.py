"""Staleness classification for agent research context.

Pure logic module - no I/O, no LLM calls.
"""

import json
from datetime import date
from enum import IntEnum


class RefreshTier(IntEnum):
    QUICK = 1
    LIGHTWEIGHT = 2
    FULL_RESTALE = 3


def get_research_date(agent) -> date:
    """Extract the research date from an agent's persona.

    Priority: persona_json["research_date"] > agent.created_at > today.
    """
    try:
        persona = json.loads(agent.persona_json)
        rd = persona.get("research_date")
        if rd:
            return date.fromisoformat(rd)
    except (json.JSONDecodeError, ValueError, TypeError):
        pass

    if agent.created_at is not None:
        return agent.created_at.date() if hasattr(agent.created_at, "date") else agent.created_at

    return date.today()


def get_staleness_thresholds(tools_json: str) -> tuple:
    """Return (tier2_days, tier3_days) based on agent tool types.

    News/social heavy: (2, 7)
    Fundamentals heavy: (7, 30)
    Default/mixed: (3, 14)
    """
    try:
        tools = json.loads(tools_json) if tools_json else []
    except (json.JSONDecodeError, TypeError):
        return (3, 14)

    if not tools:
        return (3, 14)

    tools_lower = [t.lower() for t in tools]

    news_keywords = {"news", "social", "sentiment", "reddit", "twitter"}
    fundamentals_keywords = {"fundamentals", "financial", "sec", "earnings", "balance"}

    news_count = sum(1 for t in tools_lower if any(k in t for k in news_keywords))
    fund_count = sum(1 for t in tools_lower if any(k in t for k in fundamentals_keywords))

    if news_count > fund_count and news_count > 0:
        return (2, 7)
    if fund_count > news_count and fund_count > 0:
        return (7, 30)
    return (3, 14)


def compute_staleness_days(research_date: date) -> int:
    """Return the number of days since the research date."""
    return (date.today() - research_date).days


def classify_tier(staleness_days: int, thresholds: tuple) -> RefreshTier:
    """Classify staleness into a refresh tier.

    Args:
        staleness_days: Days since research was conducted
        thresholds: (tier2_days, tier3_days) from get_staleness_thresholds
    """
    tier2_days, tier3_days = thresholds
    if staleness_days >= tier3_days:
        return RefreshTier.FULL_RESTALE
    if staleness_days >= tier2_days:
        return RefreshTier.LIGHTWEIGHT
    return RefreshTier.QUICK
