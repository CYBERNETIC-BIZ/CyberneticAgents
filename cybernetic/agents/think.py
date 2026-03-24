"""Create-from-prompt engine: LLM generates a full agent config from a strategy description."""
import json
import re
from typing import Dict

from cybernetic.llm import create_llm_client

ALLOWED_TOOLS = {"market", "social", "news", "fundamentals"}
ALLOWED_TARGET_DAYS = {1, 3, 5, 7, 14, 30}

THINK_SYSTEM_PROMPT = """\
You are an AI trading agent architect for CyberneticAgents. The user will describe a trading \
strategy or investment philosophy. Your job is to generate a complete agent configuration as JSON.

Available analyst tools (choose at least one): market, social, news, fundamentals

Respond with ONLY a JSON object with these fields:
{
  "name": "lowercase-hyphenated-name (e.g., value-tech-hunter)",
  "ticker": "one or more yfinance ticker symbols, comma-separated (e.g., AAPL or AAPL,MSFT,GOOGL)",
  "direction_bias": "bullish" or "bearish" or "neutral",
  "description": "1-2 sentence description of the agent's strategy",
  "tools": ["market", "news"],
  "analysis_system_prompt": "detailed system prompt for the agent's analysis (what to look for, how to decide)",
  "comment_system_prompt": "short prompt for generating commentary on other agents' predictions and market news",
  "analysis_temperature": 0.7,
  "comment_temperature": 0.8,
  "target_days": 7,
  "max_positions": 1,
  "personality": "brief personality trait description"
}

Rules:
- name must be lowercase, hyphens only, 3-30 chars
- ticker must be valid Yahoo Finance symbol(s); use comma-separated for multi-asset strategies
- If the strategy implies a single asset, use one ticker and set max_positions to 1
- If the strategy implies a portfolio or sector, pick the best tickers and set max_positions accordingly
- analysis_temperature between 0.0 and 2.0
- target_days must be one of: 1, 3, 5, 7, 14, 30
- tools must be from the allowed set
- analysis_system_prompt should be detailed and specific to the strategy
"""


def think_agent_config(strategy: str, config: dict) -> dict:
    """Use the configured LLM to generate an agent config from a strategy description.

    Args:
        strategy: Natural language description of the trading strategy
        config: Application config with llm_provider, quick_think_llm, etc.

    Returns:
        Validated agent config dict
    """
    client = create_llm_client(
        provider=config["llm_provider"],
        model=config["quick_think_llm"],
    )
    llm = client.get_llm()

    messages = [
        ("system", THINK_SYSTEM_PROMPT),
        ("human", strategy),
    ]
    response = llm.invoke(messages)
    content = response.content

    # Extract JSON from response — handle nested braces
    # Try matching from first { to last }
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("LLM did not return valid JSON")

    try:
        data = json.loads(content[start:end + 1])
    except json.JSONDecodeError:
        # Fallback: try simple non-nested regex
        json_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
        if not json_match:
            raise ValueError("LLM did not return valid JSON")
        data = json.loads(json_match.group())

    return validate_think_result(data)


def validate_think_result(data: dict) -> dict:
    """Validate and clamp values in a think-generated config.

    Returns the cleaned config dict.
    """
    # Name: sanitize to lowercase alphanumeric + hyphens
    name = str(data.get("name", "auto-agent")).lower()
    name = re.sub(r"[^a-z0-9-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    if len(name) < 3:
        name = "auto-agent"
    if len(name) > 30:
        name = name[:30].rstrip("-")
    data["name"] = name

    # Ticker: uppercase
    data["ticker"] = str(data.get("ticker", "SPY")).upper().strip()

    # Direction bias: must be bullish, bearish, or neutral
    bias = str(data.get("direction_bias", "neutral")).lower()
    if bias not in ("bullish", "bearish", "neutral"):
        bias = "neutral"
    data["direction_bias"] = bias

    # Description
    data["description"] = str(data.get("description", ""))[:500]

    # Tools: filter to allowed set
    tools = data.get("tools", ["market"])
    if isinstance(tools, list):
        tools = [t for t in tools if t in ALLOWED_TOOLS]
    if not tools:
        tools = ["market"]
    data["tools"] = tools

    # Prompts
    data["analysis_system_prompt"] = str(data.get("analysis_system_prompt", ""))
    data["comment_system_prompt"] = str(data.get("comment_system_prompt", ""))

    # Temperatures: clamp 0.0 - 2.0
    try:
        data["analysis_temperature"] = max(0.0, min(2.0, float(data.get("analysis_temperature", 0.7))))
    except (TypeError, ValueError):
        data["analysis_temperature"] = 0.7
    try:
        data["comment_temperature"] = max(0.0, min(2.0, float(data.get("comment_temperature", 0.8))))
    except (TypeError, ValueError):
        data["comment_temperature"] = 0.8

    # Target days: snap to nearest allowed value
    try:
        td = int(data.get("target_days", 7))
    except (TypeError, ValueError):
        td = 7
    data["target_days"] = min(ALLOWED_TARGET_DAYS, key=lambda x: abs(x - td))

    # Max positions
    try:
        mp = int(data.get("max_positions", 1))
        data["max_positions"] = max(1, min(20, mp))
    except (TypeError, ValueError):
        data["max_positions"] = 1

    # Personality
    data["personality"] = str(data.get("personality", ""))[:200]

    return data
