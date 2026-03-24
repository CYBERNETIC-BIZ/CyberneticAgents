"""News fetching and LLM sentiment summary for agent context refresh.

Tries yfinance first, falls back to Alpha Vantage if available.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List

import yfinance as yf


@dataclass
class HeadlineItem:
    title: str
    publisher: str
    publish_time: str


def _fetch_from_yfinance(ticker: str, max_items: int) -> List[HeadlineItem]:
    """Fetch headlines via yfinance. Returns empty list on failure."""
    try:
        t = yf.Ticker(ticker)
        raw = t.news
        if not raw:
            return []

        # New yfinance shape: dict with "news" key containing list
        if isinstance(raw, dict):
            items = raw.get("news", raw.get("items", []))
        else:
            items = raw

        headlines = []
        for item in items[:max_items]:
            # Handle nested content structure (newer yfinance)
            content = item.get("content", item)
            title = content.get("title", item.get("title", ""))
            publisher = content.get("provider", {})
            if isinstance(publisher, dict):
                publisher = publisher.get("displayName", "")
            else:
                publisher = item.get("publisher", str(publisher))

            pub_time = content.get("pubDate", item.get("providerPublishTime", ""))
            if isinstance(pub_time, (int, float)):
                pub_time = datetime.fromtimestamp(pub_time).strftime("%Y-%m-%d %H:%M")

            if title:
                headlines.append(HeadlineItem(
                    title=title,
                    publisher=publisher,
                    publish_time=str(pub_time),
                ))

        return headlines
    except Exception:
        return []


def _fetch_from_alpha_vantage(ticker: str, max_items: int) -> List[HeadlineItem]:
    """Fetch headlines via Alpha Vantage NEWS_SENTIMENT API. Returns empty list on failure."""
    if not os.getenv("ALPHA_VANTAGE_API_KEY"):
        return []

    try:
        from cybernetic.data.alpha_vantage_news import get_news

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        raw = get_news(ticker, start_date, end_date)

        if not raw or isinstance(raw, str) and "error" in raw.lower():
            return []

        # Alpha Vantage returns JSON string or dict
        if isinstance(raw, str):
            data = json.loads(raw)
        else:
            data = raw

        feed = data.get("feed", [])
        headlines = []
        for item in feed[:max_items]:
            title = item.get("title", "")
            source = item.get("source", "")
            pub_time = item.get("time_published", "")
            # Format: 20260305T143000 -> 2026-03-05 14:30
            if pub_time and len(pub_time) >= 13:
                try:
                    dt = datetime.strptime(pub_time[:13], "%Y%m%dT%H%M")
                    pub_time = dt.strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    pass

            if title:
                headlines.append(HeadlineItem(
                    title=title,
                    publisher=source,
                    publish_time=str(pub_time),
                ))

        return headlines
    except Exception:
        return []


def fetch_news_headlines(ticker: str, max_items: int = 10) -> List[HeadlineItem]:
    """Fetch recent news headlines for a ticker.

    Tries yfinance first, falls back to Alpha Vantage if yfinance
    returns no results and an Alpha Vantage API key is configured.
    Returns empty list if both fail.
    """
    headlines = _fetch_from_yfinance(ticker, max_items)
    if headlines:
        return headlines

    return _fetch_from_alpha_vantage(ticker, max_items)


def summarize_news_sentiment(
    headlines: List[HeadlineItem], ticker: str, llm
) -> str:
    """Send headlines to LLM for a 2-4 sentence sentiment summary.

    Returns empty string on failure.
    """
    if not headlines:
        return ""

    headlines_text = "\n".join(
        f"- [{h.publish_time}] {h.title} ({h.publisher})"
        for h in headlines
    )

    prompt = (
        f"Analyze the sentiment of these recent news headlines for {ticker}. "
        f"Provide a 2-4 sentence summary of the overall sentiment "
        f"(bullish, bearish, or neutral) and key themes:\n\n{headlines_text}"
    )

    try:
        response = llm.invoke(prompt)
        return response.content.strip()
    except Exception:
        return ""


def build_news_context_block(
    headlines: List[HeadlineItem], sentiment_summary: str = ""
) -> str:
    """Format headlines and sentiment into an injectable context block."""
    if not headlines:
        return ""

    parts = ["Recent News Headlines:"]
    for h in headlines:
        parts.append(f"  [{h.publish_time}] {h.title} ({h.publisher})")

    if sentiment_summary:
        parts.append(f"\nSentiment Summary: {sentiment_summary}")

    return "\n".join(parts)
