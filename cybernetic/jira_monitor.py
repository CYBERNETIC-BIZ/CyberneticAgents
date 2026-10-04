"""Move the linked Jira issue as agent work starts, opens a PR, and merges.

The linked key comes from ``JIRA_ISSUE_KEY``, the branch name, or the pull
request title and body. Nothing here assumes a single ticket.

Hook processes call the Jira REST API. They cannot use the Cursor Atlassian
connector. Without ``JIRA_EMAIL`` and ``JIRA_API_TOKEN`` the monitor reports
the skip and leaves the issue unchanged.

Status names on this site, matched by the destination status:

* coding starts -> In Progress
* pull request open -> In Review, plus the comment below
* pull request merged -> Done

Comment text when a pull request is open::

    In Review. Pull request: <url>
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence
from urllib.request import Request

from typing_extensions import Never

from cybernetic.agent_guard import branch_slug_denied
from cybernetic.spend import (
    CHEAP_OPENAI_MODEL,
    LIVE_RUN_PAUSE,
    MONTHLY_CAP_EUR,
    PER_RUN_CAP_EUR,
)

STATUS_IN_PROGRESS = "In Progress"
STATUS_IN_REVIEW = "In Review"
STATUS_DONE = "Done"
REVIEW_COMMENT = "In Review. Pull request: {url}"

DEFAULT_SITE_URL = "https://lgbongiolo.atlassian.net"
DEFAULT_CLOUD_ID = "b908f08c-773a-4389-beab-787b98d0bc37"

MISSING_CREDENTIALS = (
    "jira monitor: skipped because this process has no Jira API credentials. "
    "Set JIRA_EMAIL (or ATLASSIAN_EMAIL) and JIRA_API_TOKEN (or ATLASSIAN_API_TOKEN). "
    "Cursor agents can use the Atlassian connector; hook scripts and GitHub Actions cannot. "
    f"With credentials, coding start moves the linked issue to {STATUS_IN_PROGRESS}; "
    f"an open pull request moves it to {STATUS_IN_REVIEW} and comments "
    f"'{REVIEW_COMMENT.format(url='<url>')}'; "
    f"a merged pull request moves it to {STATUS_DONE}."
)

EventName = Literal["start", "stop", "merged"]
_EXPLICIT_KEY = re.compile(r"\b([A-Z][A-Z0-9]{1,10}-\d+)\b")
_EXPLICIT_TOKEN = re.compile(r"^[A-Z][A-Z0-9]{1,10}-\d+$")
_BRANCH_KEY = re.compile(r"(?:^|/)([a-z][a-z0-9]{1,10})-(\d+)(?=-|/|$)")
Opener = Callable[..., Any]


def _never(value: Never) -> None:
    raise AssertionError(f"unhandled jira event: {value}")


@dataclass(frozen=True)
class TransitionPlan:
    """What to change on one issue. A missing target means leave the status."""

    target_status: Optional[str]
    comment: Optional[str]
    reason: str


def review_comment(pr_url: str) -> str:
    return REVIEW_COMMENT.format(url=pr_url)


def resolve_ticket_keys(
    *,
    explicit: str = "",
    branch: str = "",
    title: str = "",
    body: str = "",
) -> List[str]:
    """Collect Jira keys without inventing any.

    An explicit ``JIRA_ISSUE_KEY`` list wins and is not mixed with guesses.
    Branch slugs match ``kan-6`` inside ``cursor/kan-6-...``. Uppercase keys
    match in the pull request title and body. Lowercase model names such as
    ``gpt-5`` are not treated as keys.
    """
    if explicit.strip():
        keys: List[str] = []
        seen = set()
        for token in re.split(r"[\s,]+", explicit.strip()):
            key = token.upper()
            if _EXPLICIT_TOKEN.fullmatch(key) is None:
                continue
            if key not in seen:
                seen.add(key)
                keys.append(key)
        return keys

    found: List[str] = []
    seen = set()

    def add(key: str) -> None:
        project = key.split("-", 1)[0]
        if branch_slug_denied(project):
            return
        if key not in seen:
            seen.add(key)
            found.append(key)

    for project, number in _BRANCH_KEY.findall(branch.lower()):
        if branch_slug_denied(project):
            continue
        add(f"{project.upper()}-{number}")
    for text in (title, body):
        for key in _EXPLICIT_KEY.findall(text or ""):
            add(key.upper())
    return found


def plan_transition(
    event: EventName,
    *,
    current_status: Optional[str],
    pr_state: Optional[str],
    pr_url: Optional[str],
) -> TransitionPlan:
    """Choose the status move for one event. Does not call Jira."""
    current = current_status or ""
    state = (pr_state or "").upper()
    if event == "start":
        if current in {STATUS_IN_PROGRESS, STATUS_IN_REVIEW, STATUS_DONE}:
            return TransitionPlan(None, None, f"already {current}")
        return TransitionPlan(STATUS_IN_PROGRESS, None, "coding started")
    if event == "stop":
        if state == "MERGED":
            if current == STATUS_DONE:
                return TransitionPlan(None, None, "already Done")
            return TransitionPlan(STATUS_DONE, None, "pull request merged")
        if state == "OPEN" and pr_url:
            if current == STATUS_DONE:
                return TransitionPlan(None, None, "already Done")
            target = None if current == STATUS_IN_REVIEW else STATUS_IN_REVIEW
            return TransitionPlan(target, review_comment(pr_url), "pull request open")
        return TransitionPlan(None, None, "no open pull request")
    if event == "merged":
        if current == STATUS_DONE:
            return TransitionPlan(None, None, "already Done")
        return TransitionPlan(STATUS_DONE, None, "pull request merged")
    _never(event)


def session_context(jira_message: str) -> str:
    """Context injected when a Cursor session starts."""
    return (
        "Branch rules: work on a cursor/* branch cut from agent/main. "
        "Open pull requests only into agent/main. Never push to main or master, and never merge. "
        "Only the owner merges agent/main into main. "
        "The product goal in GOALS.md is not written yet. "
        f"Spend: live model calls are opt-in via CYBERNETIC_LIVE_CALLS=1, skipped in CI, "
        f"capped at €{PER_RUN_CAP_EUR:.0f} per run and €{MONTHLY_CAP_EUR:.0f} per month, "
        f"and pause every {LIVE_RUN_PAUSE} live runs until CYBERNETIC_SPEND_CONTINUE equals that count. "
        f"Tests that call a live model must use {CHEAP_OPENAI_MODEL}. Do not loop on any API. "
        f"Jira: {jira_message}"
    )


def read_hook_input(raw: str) -> Dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


class JiraClient:
    """Minimal Jira Cloud REST client using basic auth."""

    def __init__(
        self,
        site_url: str,
        email: str,
        token: str,
        opener: Optional[Opener] = None,
    ) -> None:
        self.site_url = site_url.rstrip("/")
        self._email = email
        self._token = token
        self._opener = opener or urllib.request.urlopen

    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> Any:
        url = f"{self.site_url}{path}"
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(url, data=data, method=method)
        raw_auth = f"{self._email}:{self._token}".encode("utf-8")
        request.add_header("Authorization", "Basic " + base64.b64encode(raw_auth).decode("ascii"))
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self._opener(request, timeout=20) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:240]
            raise RuntimeError(f"Jira {method} {path} returned HTTP {exc.code}: {detail}") from exc
        if not body:
            return None
        return json.loads(body.decode("utf-8"))

    def status_name(self, issue_key: str) -> str:
        payload = self._request("GET", f"/rest/api/3/issue/{issue_key}?fields=status")
        return str(payload["fields"]["status"]["name"])

    def transition_to(self, issue_key: str, status_name: str) -> None:
        payload = self._request("GET", f"/rest/api/3/issue/{issue_key}/transitions")
        transitions = payload.get("transitions", []) if isinstance(payload, dict) else []
        match = None
        for transition in transitions:
            destination = (transition.get("to") or {}).get("name", "")
            if destination.lower() == status_name.lower():
                match = transition
                break
        if match is None:
            available = [
                (item.get("to") or {}).get("name", "?")
                for item in transitions
                if isinstance(item, dict)
            ]
            raise RuntimeError(
                f"No transition to {status_name} for {issue_key}. Available: {available}"
            )
        self._request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/transitions",
            {"transition": {"id": str(match["id"])}},
        )

    def comment_texts(self, issue_key: str) -> List[str]:
        payload = self._request("GET", f"/rest/api/3/issue/{issue_key}/comment?maxResults=50")
        comments = payload.get("comments", []) if isinstance(payload, dict) else []
        texts: List[str] = []
        for comment in comments:
            body = comment.get("body") if isinstance(comment, dict) else None
            texts.append(json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body)
        return texts

    def add_comment(self, issue_key: str, text: str) -> None:
        self._request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/comment",
            {
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": text}],
                        }
                    ],
                }
            },
        )


def credentials() -> Optional[tuple]:
    email = os.environ.get("JIRA_EMAIL") or os.environ.get("ATLASSIAN_EMAIL") or ""
    token = os.environ.get("JIRA_API_TOKEN") or os.environ.get("ATLASSIAN_API_TOKEN") or ""
    if email.strip() and token.strip():
        return email.strip(), token.strip()
    return None


def site_url() -> str:
    return (os.environ.get("JIRA_SITE_URL") or DEFAULT_SITE_URL).strip()


def current_branch() -> str:
    override = os.environ.get("GIT_BRANCH", "").strip()
    if override:
        return override
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def read_pull_request() -> Dict[str, str]:
    """Prefer env injected by CI. Fall back to ``gh pr view``."""
    if os.environ.get("PR_URL") or os.environ.get("PR_STATE") or os.environ.get("PR_TITLE"):
        return {
            "url": os.environ.get("PR_URL", ""),
            "title": os.environ.get("PR_TITLE", ""),
            "body": os.environ.get("PR_BODY", ""),
            "state": os.environ.get("PR_STATE", ""),
        }
    try:
        result = subprocess.run(
            ["gh", "pr", "view", "--json", "url,title,body,state"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
            env={**os.environ, "GH_PROMPT_DISABLED": "1"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        "url": str(payload.get("url") or ""),
        "title": str(payload.get("title") or ""),
        "body": str(payload.get("body") or ""),
        "state": str(payload.get("state") or ""),
    }


def discover_tickets(*, include_pr: bool) -> tuple:
    """Return ``(keys, pull_request)``."""
    pull_request: Dict[str, str] = read_pull_request() if include_pr else {}
    keys = resolve_ticket_keys(
        explicit=os.environ.get("JIRA_ISSUE_KEY", ""),
        branch=current_branch(),
        title=pull_request.get("title", ""),
        body=pull_request.get("body", ""),
    )
    return keys, pull_request


def apply_plan(client: JiraClient, issue_key: str, plan: TransitionPlan) -> str:
    notes: List[str] = []
    if plan.target_status:
        client.transition_to(issue_key, plan.target_status)
        notes.append(f"{issue_key} -> {plan.target_status}")
    else:
        notes.append(f"{issue_key}: status unchanged ({plan.reason})")
    if plan.comment:
        existing = client.comment_texts(issue_key)
        if any(plan.comment in text for text in existing):
            notes.append(f"{issue_key}: comment already present")
        else:
            client.add_comment(issue_key, plan.comment)
            notes.append(f"{issue_key}: commented")
    return "; ".join(notes)


def run_event(event: EventName, client: Optional[JiraClient] = None) -> str:
    """Apply ``event`` to every linked ticket. Returns a one-line result."""
    include_pr = event in {"stop", "merged"}
    keys, pull_request = discover_tickets(include_pr=include_pr)
    if not keys:
        return "jira monitor: no linked ticket on JIRA_ISSUE_KEY, the branch, or the pull request"
    creds = credentials()
    active = client
    if active is None:
        if creds is None:
            return MISSING_CREDENTIALS + " Linked tickets: " + ", ".join(keys)
        email, token = creds
        active = JiraClient(site_url(), email, token)
    notes: List[str] = []
    for key in keys:
        try:
            current = active.status_name(key)
            plan = plan_transition(
                event,
                current_status=current,
                pr_state=pull_request.get("state"),
                pr_url=pull_request.get("url"),
            )
            notes.append(apply_plan(active, key, plan))
        except Exception as exc:
            notes.append(f"{key}: {exc}")
    return "jira monitor: " + " | ".join(notes)


def on_session_start(_payload: Optional[dict] = None) -> Dict[str, str]:
    try:
        message = run_event("start")
    except Exception as exc:
        message = f"jira monitor failed and left tickets unchanged: {exc}"
    return {"additional_context": session_context(message)}


def on_stop(payload: Optional[dict] = None) -> str:
    status = (payload or {}).get("status", "")
    if status == "aborted":
        return "jira monitor: stop ignored because the agent was aborted"
    try:
        return run_event("stop")
    except Exception as exc:
        return f"jira monitor failed and left tickets unchanged: {exc}"


def _start_marker(keys: Sequence[str]) -> Path:
    safe = "-".join(key.replace("/", "") for key in keys)
    return Path(".cybernetic") / f"jira-started-{safe}"


def on_file_edit_started() -> str:
    """First coding edit uses the same In Progress move as session start.

    Later edits in this checkout reuse a local marker so each keystroke does
    not call Jira. A missing-credentials result does not write the marker.
    """
    try:
        keys, _pull = discover_tickets(include_pr=False)
        if not keys:
            return "jira monitor: no linked ticket on JIRA_ISSUE_KEY, the branch, or the pull request"
        marker = _start_marker(keys)
        if marker.exists():
            return f"jira monitor: {', '.join(keys)} already marked {STATUS_IN_PROGRESS} in this checkout"
        message = run_event("start")
    except Exception as exc:
        return f"jira monitor failed and left tickets unchanged: {exc}"
    if "->" in message or "already" in message:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(message, encoding="utf-8")
    return message


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Move linked Jira issues with agent work.")
    parser.add_argument("--event", required=True, choices=("start", "stop", "merged"))
    args = parser.parse_args(argv)
    event: EventName = args.event
    print(run_event(event))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
