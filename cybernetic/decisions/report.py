"""Plain-text rendering of Laya and Jev outcomes."""

from typing import Any, Dict, List, Optional, Sequence

from cybernetic.decisions.types import ProviderOutcome


def _nearest_legend(score: float, legend: object) -> Optional[str]:
    if not isinstance(legend, dict) or not legend:
        return None
    best_label: Optional[str] = None
    best_distance: Optional[float] = None
    for key, label in legend.items():
        try:
            level = float(key)
        except (TypeError, ValueError):
            continue
        distance = abs(level - score)
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_label = label if isinstance(label, str) else str(label)
    return best_label


def format_answer(answer: object) -> str:
    """Format one System One answer. Unknown shapes stay visible."""
    if not isinstance(answer, dict):
        return "unrecognized answer"
    kind = answer.get("type")
    if kind == "choice":
        choice = answer.get("choice", "?")
        confidence = answer.get("confidence")
        if isinstance(confidence, (int, float)):
            return f"{choice} (confidence {confidence:.2f})"
        return str(choice)
    if kind == "score":
        score = answer.get("score")
        if not isinstance(score, (int, float)):
            return "score ?"
        legend = _nearest_legend(float(score), answer.get("legend"))
        confidence = answer.get("confidence")
        detail = []
        if legend:
            detail.append(legend)
        if isinstance(confidence, (int, float)):
            detail.append(f"confidence {confidence:.2f}")
        rendered = f"{float(score):.2f}"
        if detail:
            return f"{rendered} ({', '.join(detail)})"
        return rendered
    if kind == "noul":
        noul = answer.get("noul")
        if isinstance(noul, (int, float)):
            return f"yes-probability {float(noul):.2f}"
        return "yes-probability ?"
    return f"unrecognized answer type: {kind}"


def render_report(state: str, outcomes: Sequence[ProviderOutcome]) -> str:
    """Render providers sequentially, each under its own label."""
    lines: List[str] = ["Decision", f"state: {state}", ""]
    for outcome in outcomes:
        lines.append(f"== {outcome.provider} ==")
        if outcome.model:
            lines.append(f"model: {outcome.model}")
        if outcome.skipped:
            lines.append(f"skipped: {outcome.skipped}")
        elif outcome.error:
            lines.append(f"error: {outcome.error}")
        elif outcome.answers:
            for key, answer in outcome.answers.items():
                lines.append(f"{key}: {format_answer(answer)}")
        else:
            lines.append("error: provider returned no answers")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def answers_from_payload(payload: Dict[str, Any]) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Pull ``(model, answers)`` out of a Laya or Jev response."""
    routing = payload.get("routing")
    model = None
    if isinstance(routing, dict):
        routed = routing.get("model")
        if isinstance(routed, str) and routed:
            model = routed
    if model is None:
        raw_model = payload.get("model")
        if isinstance(raw_model, str) and raw_model:
            model = raw_model
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        return model, None
    return model, answers
