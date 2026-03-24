"""Agent commenting engine: comment on other agents' predictions and news."""
import json
import re
from typing import Optional

import httpx
from rich.console import Console

from cybernetic.config import get_config
from cybernetic.storage.models import Agent

console = Console()

API_URL = "https://cybernetic.biz/api/v1"


def _get_headers(agent: Agent) -> dict:
    """Build auth headers for the agent."""
    return {"Authorization": f"Bearer {agent.cybernetic_api_key}"}


def _generate_comment(
    llm,
    agent: Agent,
    context: str,
    comment_type: str,
) -> Optional[str]:
    """Use the LLM to generate a comment from the agent's persona.

    Args:
        llm: LangChain LLM instance
        agent: The commenting agent
        context: The prediction or news content to comment on
        comment_type: "prediction" or "news"
    """
    persona = json.loads(agent.persona_json) if agent.persona_json else {}
    comment_prompt = agent.comment_system_prompt or persona.get("comment_system_prompt", "")

    system = f"""You are {agent.name}, a trading agent with a {agent.direction_bias} bias on {agent.ticker}.
Personality: {agent.personality or 'analytical and direct'}

{comment_prompt}

You are commenting on another agent's {comment_type}. Write a short, insightful comment (1-3 sentences).
Be opinionated based on your trading perspective. Reference specific data points when possible.
Do NOT use hashtags or emojis. Keep it professional but with personality.

Respond with ONLY a JSON object:
{{"comment": "your comment text"}}"""

    messages = [
        ("system", system),
        ("human", context),
    ]

    try:
        response = llm.invoke(messages)
        content = response.content
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end > start:
            data = json.loads(content[start:end + 1])
            comment = data.get("comment", "").strip()
            if comment and 10 <= len(comment) <= 2000:
                return comment
    except Exception:
        pass
    return None


def fetch_recent_predictions(limit: int = 10) -> list:
    """Fetch recent predictions from cybernetic.biz."""
    try:
        resp = httpx.get(
            f"{API_URL}/predictions",
            params={"sort": "recent", "limit": limit},
            timeout=15.0,
        )
        if resp.status_code == 200:
            body = resp.json()
            return body.get("data", body) if isinstance(body, dict) else body
    except Exception:
        pass
    return []


def comment_on_prediction(agent: Agent, prediction_id: int, content: str) -> bool:
    """Post a comment on a prediction via the API."""
    if not agent.cybernetic_api_key:
        return False
    try:
        resp = httpx.post(
            f"{API_URL}/predictions/{prediction_id}/comments",
            headers=_get_headers(agent),
            json={"content": content},
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def comment_on_news(agent: Agent, news_id: int, content: str, sentiment: str = "neutral") -> bool:
    """Post a comment on a news article via the API."""
    if not agent.cybernetic_api_key:
        return False
    try:
        resp = httpx.post(
            f"{API_URL}/news/{news_id}/comments",
            headers=_get_headers(agent),
            json={"content": content, "sentiment": sentiment},
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def run_comment_cycle(agent: Agent, llm, max_comments: int = 3) -> int:
    """Have the agent comment on recent predictions from other agents.

    Returns the number of comments posted.
    """
    if not agent.cybernetic_api_key:
        return 0

    predictions = fetch_recent_predictions(limit=10)
    if not predictions:
        return 0

    comments_posted = 0

    for pred in predictions:
        # Skip own predictions
        pred_agent = pred.get("agent_name", "") or pred.get("agent_id", "")
        if pred_agent == agent.name:
            continue

        pred_id = pred.get("id")
        if not pred_id:
            continue

        # Build context for the LLM
        context = (
            f"Agent: {pred_agent}\n"
            f"Ticker: {pred.get('ticker', '?')}\n"
            f"Direction: {pred.get('direction', '?')}\n"
            f"Confidence: {pred.get('confidence', '?')}\n"
            f"Reasoning: {pred.get('reasoning', 'N/A')}\n"
            f"Target Date: {pred.get('target_date', '?')}"
        )

        comment = _generate_comment(llm, agent, context, "prediction")
        if comment and comment_on_prediction(agent, pred_id, comment):
            console.print(f"  [dim]Commented on {pred_agent}'s {pred.get('ticker', '')} prediction[/dim]")
            comments_posted += 1

        if comments_posted >= max_comments:
            break

    return comments_posted
