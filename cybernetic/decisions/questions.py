"""Typed questions shared by Laya and Jev.

The built-in set only exercises the three System One answer types. It is not
a product goal. Replace it with ``--questions`` when the owner defines one.
"""

import json
from pathlib import Path
from typing import Any, Dict

DEFAULT_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "label": {
        "type": "choice",
        "instructions": "Which label best fits this text?",
        "criteria": {
            "positive": "favorable, opportunity, or agreement",
            "negative": "risk, complaint, or disagreement",
            "neutral": "neither clearly favorable nor unfavorable",
        },
    },
    "intensity": {
        "type": "score",
        "instructions": "How strong is the stance in this text?",
        "criteria": ["none", "mild", "strong"],
    },
    "actionable": {
        "type": "noul",
        "instructions": "Does this text ask for a concrete next action?",
    },
}

_QUESTION_TYPES = frozenset({"choice", "score", "noul"})


def load_questions(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load a questions object from JSON.

    Raises:
        ValueError: The file is not a non-empty object of typed questions.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"questions file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise ValueError("questions file must be a non-empty JSON object")
    for key, question in data.items():
        if not isinstance(key, str) or not key:
            raise ValueError("each question key must be a non-empty string")
        if not isinstance(question, dict):
            raise ValueError(f"question {key!r} must be a JSON object")
        kind = question.get("type")
        if kind not in _QUESTION_TYPES:
            raise ValueError(
                f"question {key!r} must set type to choice, score, or noul"
            )
    return data
