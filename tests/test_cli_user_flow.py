"""User-flow coverage for the CLI, including Laya and Jev side by side."""

import json

from tests.cli_harness import FIXTURES, CliHarness, default_decision_harness


def test_user_compares_laya_and_jev_then_uses_nearby_commands(tmp_path, monkeypatch):
    ledger = tmp_path / "spend.json"
    monkeypatch.setenv("CYBERNETIC_SPEND_LEDGER", str(ledger))
    harness = default_decision_harness()
    harness.env["CYBERNETIC_SPEND_LEDGER"] = str(ledger)

    help_result = harness.invoke(["--help"])
    assert help_result.exit_code == 0
    assert "decide" in help_result.stdout
    assert "dashboard" in help_result.stdout
    assert "schedule" in help_result.stdout

    decision = harness.invoke(
        ["decide", "We were billed twice. Please refund the duplicate today."]
    )
    assert decision.exit_code == 0, decision.stdout + decision.stderr
    output = decision.stdout
    assert output.index("== Laya ==") < output.index("== Jev ==")
    assert "model: english" in output
    assert "model: jev-1.13.0" in output
    assert "label: negative (confidence 0.74)" in output
    assert "label: negative (confidence 0.66)" in output
    assert "actionable: yes-probability 0.91" in output
    assert "actionable: yes-probability 0.80" in output
    assert not ledger.exists()

    questions = tmp_path / "questions.json"
    questions.write_text(
        json.dumps(
            {
                "refund": {
                    "type": "noul",
                    "instructions": "Does this ask for a refund?",
                }
            }
        ),
        encoding="utf-8",
    )
    custom = harness.invoke(["decide", "Please refund the duplicate.", "--questions", str(questions)])
    assert custom.exit_code == 0
    assert "== Laya ==" in custom.stdout and "== Jev ==" in custom.stdout

    dashboard = harness.invoke(["dashboard"])
    assert dashboard.exit_code == 0
    assert "No agents found" in dashboard.stdout

    schedule = harness.invoke(["schedule", "demo-agent", "--daily", "09:30"])
    assert schedule.exit_code == 0
    assert "demo-agent" in schedule.stdout
    assert "crontab" in schedule.stdout


def test_decide_rejects_an_empty_question_file(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{}", encoding="utf-8")
    result = CliHarness(
        laya_fixture=FIXTURES / "laya_response.json",
        jev_fixture=FIXTURES / "jev_response.json",
    ).invoke(["decide", "hello", "--questions", str(path)])
    assert result.exit_code == 1
    assert "non-empty" in result.stdout
