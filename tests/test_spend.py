"""Spend guard: opt-in, caps, pause, and the cheap OpenAI model."""

import json

import pytest

from cybernetic.spend import (
    CHEAP_OPENAI_MODEL,
    CONTINUE_ENV,
    LIVE_CALLS_ENV,
    LIVE_RUN_PAUSE,
    MONTHLY_CAP_EUR,
    PER_RUN_CAP_EUR,
    SKIP_CI,
    SKIP_ENV,
    SpendGuard,
    get_guard,
    micro_eur_for,
    reset_guard_cache,
)


@pytest.fixture
def allow_live_budget(isolate_live_spend, monkeypatch):
    """Opt this test into the guard. isolate_live_spend still points at a temp ledger."""
    monkeypatch.delenv(SKIP_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(CONTINUE_ENV, raising=False)
    monkeypatch.setenv(LIVE_CALLS_ENV, "1")


def _call(guard: SpendGuard, *, provider="laya", model="laya", output_tokens=0, input_tokens=32):
    return guard.authorize(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def test_live_calls_are_blocked_unless_opted_in(tmp_path, monkeypatch):
    monkeypatch.delenv(SKIP_ENV, raising=False)
    monkeypatch.delenv(LIVE_CALLS_ENV, raising=False)
    monkeypatch.delenv("CI", raising=False)
    decision = _call(SpendGuard(tmp_path / "spend.json"))
    assert not decision.allowed
    assert "CYBERNETIC_LIVE_CALLS=1" in decision.reason
    assert not (tmp_path / "spend.json").exists()


def test_live_calls_are_skipped_in_ci_even_when_opted_in(tmp_path, monkeypatch):
    monkeypatch.delenv(SKIP_ENV, raising=False)
    monkeypatch.setenv(LIVE_CALLS_ENV, "1")
    monkeypatch.setenv("CI", "true")
    decision = _call(SpendGuard(tmp_path / "spend.json"), provider="openai", model=CHEAP_OPENAI_MODEL)
    assert not decision.allowed
    assert decision.reason == SKIP_CI


def test_openai_live_tests_must_use_the_cheap_model(allow_live_budget, tmp_path):
    guard = SpendGuard(tmp_path / "spend.json")
    refused = _call(guard, provider="openai", model="gpt-5.2", input_tokens=100, output_tokens=50)
    assert not refused.allowed
    assert CHEAP_OPENAI_MODEL in refused.reason
    allowed = _call(guard, provider="openai", model=CHEAP_OPENAI_MODEL, input_tokens=100, output_tokens=50)
    assert allowed.allowed
    assert allowed.estimated_eur > 0


def test_pause_every_ten_live_runs_until_explicit_continue(allow_live_budget, tmp_path, monkeypatch):
    guard = SpendGuard(tmp_path / "spend.json")
    for _ in range(LIVE_RUN_PAUSE):
        assert _call(guard).allowed
    paused = _call(guard)
    assert not paused.allowed
    assert f"{CONTINUE_ENV}={LIVE_RUN_PAUSE}" in paused.reason

    monkeypatch.setenv(CONTINUE_ENV, str(LIVE_RUN_PAUSE))
    assert _call(guard).allowed
    for _ in range(LIVE_RUN_PAUSE - 1):
        assert _call(guard).allowed
    paused_again = _call(guard)
    assert not paused_again.allowed
    assert f"{CONTINUE_ENV}={LIVE_RUN_PAUSE * 2}" in paused_again.reason


def test_per_run_cap_is_well_under_the_monthly_cap():
    assert PER_RUN_CAP_EUR < MONTHLY_CAP_EUR
    assert PER_RUN_CAP_EUR <= 1.0
    assert MONTHLY_CAP_EUR == 20.0


def test_per_run_euro_cap_blocks_before_the_call(allow_live_budget, tmp_path):
    guard = SpendGuard(tmp_path / "spend.json")
    # 5_000_000 output tokens of gpt-5-nano reserve about €2, over the €1 run cap.
    decision = _call(
        guard,
        provider="openai",
        model=CHEAP_OPENAI_MODEL,
        input_tokens=1,
        output_tokens=5_000_000,
    )
    assert not decision.allowed
    assert "Per-run spend cap" in decision.reason
    assert not (tmp_path / "spend.json").exists()


def test_monthly_euro_cap_blocks_before_the_call(allow_live_budget, tmp_path):
    ledger = tmp_path / "spend.json"
    ledger.write_text(
        json.dumps(
            {
                "month": SpendGuard(ledger)._month_key(),
                "month_micro_eur": 19_900_000,
                "live_runs": 1,
                "acknowledged_pause": 0,
            }
        ),
        encoding="utf-8",
    )
    decision = _call(
        SpendGuard(ledger),
        provider="openai",
        model=CHEAP_OPENAI_MODEL,
        input_tokens=1,
        output_tokens=5_000_000,
    )
    assert not decision.allowed
    assert "Monthly spend cap" in decision.reason
    saved = json.loads(ledger.read_text(encoding="utf-8"))
    assert saved["live_runs"] == 1
    assert saved["month_micro_eur"] == 19_900_000


def test_documented_prices_match_the_reservation(allow_live_budget):
    # gpt-5-nano: $0.05 / 1M input and $0.40 / 1M output, counted 1 USD = 1 EUR.
    one_million_in = micro_eur_for("openai", 1_000_000, 0)
    one_million_out = micro_eur_for("openai", 0, 1_000_000)
    assert one_million_in == 50_000
    assert one_million_out == 400_000
    # Jev input $0.042 / 1M, output $0.
    assert micro_eur_for("jev", 1_000_000, 500) == 42_000
    assert micro_eur_for("laya", 1_000_000, 1_000_000) == 0


def test_get_guard_uses_the_test_ledger(allow_live_budget, tmp_path, monkeypatch):
    ledger = tmp_path / "isolated.json"
    monkeypatch.setenv("CYBERNETIC_SPEND_LEDGER", str(ledger))
    reset_guard_cache()
    decision = get_guard().authorize(
        provider="laya",
        model="laya",
        input_tokens=8,
        output_tokens=0,
    )
    assert decision.allowed
    assert json.loads(ledger.read_text(encoding="utf-8"))["live_runs"] == 1
