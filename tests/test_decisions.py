"""Laya and Jev wiring. Fixtures stand in for checkpoints and the Jev API."""

import json
from pathlib import Path

import httpx

from cybernetic.decisions.jev import DEFAULT_MODEL, JevProvider
from cybernetic.decisions.laya import LayaProvider
from cybernetic.decisions.questions import DEFAULT_QUESTIONS, load_questions
from cybernetic.decisions.runner import default_providers, run_decision
from cybernetic.spend import SKIP_ENV, get_guard, reset_guard_cache

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_default_providers_are_laya_then_jev():
    assert [provider.name for provider in default_providers()] == ["Laya", "Jev"]


def test_fixture_report_labels_both_models(monkeypatch):
    monkeypatch.setenv("CYBERNETIC_LAYA_FIXTURE", str(FIXTURES / "laya_response.json"))
    monkeypatch.setenv("CYBERNETIC_JEV_FIXTURE", str(FIXTURES / "jev_response.json"))
    report = run_decision("We were billed twice. Please refund the duplicate.")
    laya_at = report.index("== Laya ==")
    jev_at = report.index("== Jev ==")
    assert laya_at < jev_at
    assert "model: english" in report
    assert "model: jev-1.13.0" in report
    assert "confidence 0.74" in report
    assert "confidence 0.66" in report
    assert "yes-probability 0.91" in report
    assert "yes-probability 0.80" in report
    assert "mild" in report


def test_fixtures_do_not_reserve_spend(monkeypatch, tmp_path):
    ledger = tmp_path / "spend.json"
    monkeypatch.setenv("CYBERNETIC_SPEND_LEDGER", str(ledger))
    reset_guard_cache()
    monkeypatch.setenv("CYBERNETIC_LAYA_FIXTURE", str(FIXTURES / "laya_response.json"))
    monkeypatch.setenv("CYBERNETIC_JEV_FIXTURE", str(FIXTURES / "jev_response.json"))
    run_decision("hello")
    assert not ledger.exists()


def test_skipped_live_calls_name_both_providers(monkeypatch):
    monkeypatch.delenv("CYBERNETIC_LAYA_FIXTURE", raising=False)
    monkeypatch.delenv("CYBERNETIC_JEV_FIXTURE", raising=False)
    report = run_decision("hello")
    assert "== Laya ==" in report
    assert "== Jev ==" in report
    assert report.count("No API request was sent") == 2


def test_jev_posts_one_systemone_request_when_opted_in(isolate_live_spend, monkeypatch, tmp_path):
    monkeypatch.delenv(SKIP_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("CYBERNETIC_LIVE_CALLS", "1")
    monkeypatch.delenv("CYBERNETIC_JEV_FIXTURE", raising=False)
    ledger = tmp_path / "jev-spend.json"
    monkeypatch.setenv("CYBERNETIC_SPEND_LEDGER", str(ledger))
    reset_guard_cache()
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content.decode("utf-8"))
        payload = json.loads((FIXTURES / "jev_response.json").read_text(encoding="utf-8"))
        return httpx.Response(200, json=payload)

    outcome = JevProvider(api_key="test-key", transport=httpx.MockTransport(handler)).evaluate(
        "Please refund the duplicate charge.",
        DEFAULT_QUESTIONS,
    )
    assert outcome.provider == "Jev"
    assert outcome.model == "jev-1.13.0"
    assert outcome.answers["actionable"]["noul"] == 0.8
    assert seen["url"] == "https://api.typesafe.ai/v1/systemone"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == DEFAULT_MODEL
    assert seen["body"]["state"] == "Please refund the duplicate charge."
    assert set(seen["body"]["questions"]) == set(DEFAULT_QUESTIONS)
    assert json.loads(ledger.read_text(encoding="utf-8"))["live_runs"] == 1
    assert get_guard()._run_micro > 0


def test_jev_without_a_key_does_not_call_the_network(isolate_live_spend, monkeypatch):
    monkeypatch.delenv(SKIP_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("CYBERNETIC_LIVE_CALLS", "1")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Jev sent a request without an API key")

    outcome = JevProvider(api_key="", transport=httpx.MockTransport(handler)).evaluate(
        "hello",
        DEFAULT_QUESTIONS,
    )
    assert outcome.skipped is not None
    assert "TYPESAFE_API_KEY" in outcome.skipped


def test_laya_fixture_does_not_import_the_package(monkeypatch):
    monkeypatch.setenv("CYBERNETIC_LAYA_FIXTURE", str(FIXTURES / "laya_response.json"))
    outcome = LayaProvider().evaluate("hello", DEFAULT_QUESTIONS)
    assert outcome.model == "english"
    assert outcome.answers["label"]["choice"] == "negative"


def test_load_questions_rejects_a_bad_file(tmp_path):
    path = tmp_path / "questions.json"
    path.write_text('{"label": {"type": "essay"}}', encoding="utf-8")
    try:
        load_questions(path)
    except ValueError as exc:
        assert "choice, score, or noul" in str(exc)
    else:
        raise AssertionError("expected ValueError")
