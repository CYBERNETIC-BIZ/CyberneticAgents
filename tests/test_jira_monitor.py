"""Jira monitor planning and REST wiring. No live Jira calls."""

import json

from cybernetic.jira_monitor import (
    JiraClient,
    plan_transition,
    resolve_ticket_keys,
    review_comment,
    run_event,
)


def test_ticket_keys_come_from_the_branch_pr_or_explicit_value():
    assert resolve_ticket_keys(branch="cursor/kan-6-autonomous-setup-dccb") == ["KAN-6"]
    assert resolve_ticket_keys(branch="cursor/gpt-5-nano-fix") == []
    assert resolve_ticket_keys(title="Ship it", body="See KAN-6. Model note GPT-5.") == ["KAN-6"]
    assert resolve_ticket_keys(
        explicit="kan-12, not-a-key",
        branch="cursor/kan-6-autonomous-setup-dccb",
    ) == ["KAN-12"]


def test_status_plan_matches_the_owner_rule():
    start = plan_transition("start", current_status="Idea", pr_state=None, pr_url=None)
    assert start.target_status == "In Progress"
    assert start.comment is None

    already = plan_transition("start", current_status="In Review", pr_state=None, pr_url=None)
    assert already.target_status is None

    url = "https://github.com/CYBERNETIC-BIZ/CyberneticAgents/pull/7"
    review = plan_transition("stop", current_status="In Progress", pr_state="OPEN", pr_url=url)
    assert review.target_status == "In Review"
    assert review.comment == review_comment(url)
    assert url in review.comment

    done = plan_transition("merged", current_status="In Review", pr_state="MERGED", pr_url=url)
    assert done.target_status == "Done"
    assert done.comment is None

    idle = plan_transition("stop", current_status="In Progress", pr_state=None, pr_url=None)
    assert idle.target_status is None
    assert idle.reason == "no open pull request"


class _Response:
    def __init__(self, payload):
        self._payload = b"" if payload is None else json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_open_pull_request_transitions_and_comments(monkeypatch):
    monkeypatch.setenv("JIRA_ISSUE_KEY", "KAN-6")
    monkeypatch.setenv("GIT_BRANCH", "cursor/kan-6-autonomous-setup-dccb")
    monkeypatch.setenv("PR_STATE", "OPEN")
    monkeypatch.setenv("PR_URL", "https://github.com/CYBERNETIC-BIZ/CyberneticAgents/pull/7")
    monkeypatch.setenv("PR_TITLE", "[agent] Setup autonomous improvement system")
    monkeypatch.setenv("PR_BODY", "Linked ticket KAN-6")
    calls = []

    def opener(request, timeout=20):
        calls.append((request.get_method(), request.full_url, request.data))
        if request.get_method() == "GET" and "fields=status" in request.full_url:
            return _Response({"fields": {"status": {"name": "In Progress"}}})
        if request.get_method() == "GET" and request.full_url.endswith("/transitions"):
            return _Response({"transitions": [{"id": "41", "to": {"name": "In Review"}}]})
        if request.get_method() == "GET" and "/comment" in request.full_url:
            return _Response({"comments": []})
        return _Response(None)

    client = JiraClient("https://lgbongiolo.atlassian.net", "owner@example.com", "token", opener=opener)
    message = run_event("stop", client=client)
    assert "KAN-6 -> In Review" in message
    posted = [json.loads(body.decode("utf-8")) for method, _url, body in calls if method == "POST" and body]
    assert {"transition": {"id": "41"}} in posted
    comment_bodies = [item for item in posted if "body" in item]
    rendered = json.dumps(comment_bodies)
    assert "In Review. Pull request: https://github.com/CYBERNETIC-BIZ/CyberneticAgents/pull/7" in rendered
