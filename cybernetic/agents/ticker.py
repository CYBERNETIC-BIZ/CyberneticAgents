"""Ticker validation and resolution layer.

Resolves user input (aliases, company names, crypto shorthand) to valid
yfinance ticker symbols. Falls back to LLM resolution when static lookup fails.
"""
import io
import logging
import os
import re
import sys
from contextlib import contextmanager
from typing import Optional

import yfinance as yf


@contextmanager
def _suppress_yfinance_noise():
    """Suppress yfinance's noisy stderr/stdout output (HTTP 404s, delisted warnings)."""
    old_stderr = sys.stderr
    old_stdout = sys.stdout
    yf_logger = logging.getLogger("yfinance")
    old_level = yf_logger.level
    yf_logger.setLevel(logging.CRITICAL)
    sys.stderr = io.StringIO()
    sys.stdout = io.StringIO()
    old_env = os.environ.get("PYTHONWARNINGS")
    os.environ["PYTHONWARNINGS"] = "ignore"
    try:
        yield
    finally:
        sys.stderr = old_stderr
        sys.stdout = old_stdout
        yf_logger.setLevel(old_level)
        if old_env is None:
            os.environ.pop("PYTHONWARNINGS", None)
        else:
            os.environ["PYTHONWARNINGS"] = old_env

# ---------------------------------------------------------------------------
# Alias map: common names / shorthand -> yfinance symbol
# ---------------------------------------------------------------------------
_ALIASES: dict[str, str] = {
    # Crypto
    "BTC": "BTC-USD",
    "BTCUSD": "BTC-USD",
    "BITCOIN": "BTC-USD",
    "ETH": "ETH-USD",
    "ETHUSD": "ETH-USD",
    "ETHEREUM": "ETH-USD",
    "SOL": "SOL-USD",
    "SOLUSD": "SOL-USD",
    "SOLANA": "SOL-USD",
    "XRP": "XRP-USD",
    "XRPUSD": "XRP-USD",
    "RIPPLE": "XRP-USD",
    "DOGE": "DOGE-USD",
    "DOGEUSD": "DOGE-USD",
    "DOGECOIN": "DOGE-USD",
    "ADA": "ADA-USD",
    "ADAUSD": "ADA-USD",
    "CARDANO": "ADA-USD",
    "DOT": "DOT-USD",
    "DOTUSD": "DOT-USD",
    "POLKADOT": "DOT-USD",
    "AVAX": "AVAX-USD",
    "AVAXUSD": "AVAX-USD",
    "AVALANCHE": "AVAX-USD",
    "MATIC": "MATIC-USD",
    "POLYGON": "MATIC-USD",
    "LINK": "LINK-USD",
    "CHAINLINK": "LINK-USD",
    "BNB": "BNB-USD",
    "BNBUSD": "BNB-USD",
    # Indexes
    "NASDAQ": "QQQ",
    "NDX": "QQQ",
    "NASDAQ100": "QQQ",
    "SP500": "SPY",
    "S&P500": "SPY",
    "S&P": "SPY",
    "SNP500": "SPY",
    "DOWJONES": "DIA",
    "DOW": "DIA",
    "DJIA": "DIA",
    "RUSSELL": "IWM",
    "RUSSELL2000": "IWM",
    "SMALLCAP": "IWM",
    "VIX": "^VIX",
    # Commodities
    "GOLD": "GLD",
    "SILVER": "SLV",
    "OIL": "USO",
    "CRUDEOIL": "USO",
    "NATURALGAS": "UNG",
    "NATGAS": "UNG",
    # Company names
    "GOOGLE": "GOOGL",
    "ALPHABET": "GOOGL",
    "AMAZON": "AMZN",
    "FACEBOOK": "META",
    "FB": "META",
    "APPLE": "AAPL",
    "MICROSOFT": "MSFT",
    "TESLA": "TSLA",
    "NVIDIA": "NVDA",
    "NETFLIX": "NFLX",
    "BERKSHIRE": "BRK-B",
    "JPMORGAN": "JPM",
    "WALMART": "WMT",
    "DISNEY": "DIS",
    "VISA": "V",
    "MASTERCARD": "MA",
    "PAYPAL": "PYPL",
    "AMD": "AMD",
    "INTEL": "INTC",
    "UBER": "UBER",
    "AIRBNB": "ABNB",
    "COINBASE": "COIN",
    "PALANTIR": "PLTR",
    "SNOWFLAKE": "SNOW",
    "SHOPIFY": "SHOP",
    "SPOTIFY": "SPOT",
    "SNAPCHAT": "SNAP",
    "SNAP": "SNAP",
    "PINTEREST": "PINS",
    "TWITTER": "X",
    "ROBINHOOD": "HOOD",
}

_TICKER_RE = re.compile(r"^[A-Z0-9/.=^-]{1,10}$")


def normalize_ticker(raw: str) -> str:
    """Look up *raw* in the alias map. Returns the mapped symbol or the
    uppercased input if no alias exists."""
    key = raw.strip().upper().replace(" ", "")
    return _ALIASES.get(key, key)


def validate_ticker_format(ticker: str) -> bool:
    """Return True if *ticker* matches the yfinance symbol regex."""
    return bool(_TICKER_RE.match(ticker))


def validate_ticker_yfinance(ticker: str) -> bool:
    """Return True if yfinance returns price data for *ticker*."""
    try:
        with _suppress_yfinance_noise():
            hist = yf.Ticker(ticker).history(period="5d")
            return not hist.empty
    except Exception:
        return False


def resolve_ticker_llm(raw: str, config: dict) -> Optional[str]:
    """Ask the configured LLM to resolve *raw* to a yfinance ticker.

    Returns the resolved ticker string or None if the LLM cannot help.
    """
    from cybernetic.llm import create_llm_client

    try:
        client = create_llm_client(
            provider=config["llm_provider"],
            model=config["quick_think_llm"],
        )
        llm = client.get_llm()

        messages = [
            (
                "system",
                "You are a financial data assistant. The user will give you a company name, "
                "ticker shorthand, or asset description. Respond with ONLY the correct "
                "Yahoo Finance (yfinance) ticker symbol, nothing else. If you cannot "
                "determine the ticker, respond with UNKNOWN.",
            ),
            ("human", f"What is the yfinance ticker symbol for: {raw}"),
        ]
        response = llm.invoke(messages)
        candidate = response.content.strip().upper()
        if candidate and candidate != "UNKNOWN" and validate_ticker_format(candidate):
            return candidate
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Public pipeline
# ---------------------------------------------------------------------------


def resolve_ticker(raw: str, config: Optional[dict] = None) -> str:
    """Full resolution pipeline: alias -> format check -> yfinance -> LLM -> error.

    Returns a validated yfinance ticker symbol.
    Raises ValueError if the ticker cannot be resolved.
    """
    if not raw or not raw.strip():
        raise ValueError("Ticker cannot be empty")

    # Step 1: alias map
    ticker = normalize_ticker(raw)

    # Step 2: format check + yfinance validation
    if validate_ticker_format(ticker) and validate_ticker_yfinance(ticker):
        return ticker

    # Step 3: try the raw input directly (maybe it's already valid)
    raw_upper = raw.strip().upper()
    if raw_upper != ticker and validate_ticker_format(raw_upper) and validate_ticker_yfinance(raw_upper):
        return raw_upper

    # Step 4: LLM fallback
    if config:
        llm_result = resolve_ticker_llm(raw, config)
        if llm_result and validate_ticker_yfinance(llm_result):
            return llm_result

    raise ValueError(
        f"Could not resolve '{raw}' to a valid ticker. "
        "Please enter a valid yfinance symbol (e.g., AAPL, BTC-USD, SPY)."
    )


def resolve_tickers(raw: str, config: Optional[dict] = None) -> str:
    """Resolve a possibly comma-separated list of tickers.

    Splits on commas, resolves each individually, and returns them
    joined with commas.  Raises ValueError if *any* ticker fails.
    """
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise ValueError("Ticker cannot be empty")

    if len(parts) == 1:
        return resolve_ticker(parts[0], config=config)

    resolved = []
    failed = []
    for part in parts:
        try:
            resolved.append(resolve_ticker(part, config=config))
        except ValueError:
            failed.append(part)

    if failed:
        raise ValueError(
            f"Could not resolve the following tickers: {', '.join(failed)}. "
            "Please enter valid yfinance symbols (e.g., AAPL, BTC-USD, SPY)."
        )

    return ",".join(resolved)
