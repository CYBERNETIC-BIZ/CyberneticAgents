"""Cursor hook behavior: branch rules, spend loops, and secret edits."""

import json
import subprocess
from pathlib import Path

from cybernetic.agent_guard import review_shell_command, secret_edit_warning

ROOT = Path(__file__).resolve().parents[1]


def test_shell_guard_protects_main_and_blocks_api_loops():
    branch = "cursor/kan-6-autonomous-setup-dccb"
    assert review_shell_command("pytest", branch)["permission"] == "allow"
    assert review_shell_command(
        "git push -u origin cursor/kan-6-autonomous-setup-dccb",
        branch,
    )["permission"] == "allow"
    assert review_shell_command(
        "gh pr create --base agent/main --title '[agent] Setup'",
        branch,
    )["permission"] == "allow"
    assert review_shell_command("git push origin agent/main", branch)["permission"] == "allow"

    denied = review_shell_command("git push origin main", branch)
    assert denied["permission"] == "deny"
    assert "main" in denied["agent_message"]
    assert review_shell_command("git push origin HEAD:master", branch)["permission"] == "deny"
    assert review_shell_command("git commit -m 'wip'", "main")["permission"] == "deny"
    assert review_shell_command("gh pr create --title 'x'", branch)["permission"] == "deny"
    assert review_shell_command("gh pr create --base master --title x", branch)["permission"] == "deny"
    assert review_shell_command("gh pr merge 1", branch)["permission"] == "deny"

    loop = review_shell_command(
        "while true; do curl https://api.openai.com/v1/chat/completions; done",
        branch,
    )
    assert loop["permission"] == "deny"
    assert "loop" in loop["agent_message"].lower()
    quoted = review_shell_command(
        'git commit -m "while calling api.openai.com"',
        branch,
    )
    assert quoted["permission"] == "allow"
    unlock = review_shell_command("export CYBERNETIC_SPEND_CONTINUE=10", branch)
    assert unlock["permission"] == "deny"


def test_secret_edit_warning_ignores_the_example_env():
    assert secret_edit_warning("/tmp/.env", []) is not None
    assert secret_edit_warning("/tmp/.env.example", [{"new_string": "OPENAI_API_KEY="}]) is None
    warning = secret_edit_warning(
        "/tmp/settings.py",
        [{"new_string": "OPENAI_API_KEY = 'sk-live-secret-value'"}],
    )
    assert warning is not None
    assert "credential" in warning.lower()


def test_hook_scripts_emit_json():
    before = subprocess.run(
        ["python3", ".cursor/hooks/before_shell.py"],
        input=json.dumps({"command": "git push origin main", "cwd": str(ROOT)}),
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    assert before.returncode == 0, before.stderr
    assert json.loads(before.stdout)["permission"] == "deny"

    allowed = subprocess.run(
        ["python3", ".cursor/hooks/before_shell.py"],
        input=json.dumps({"command": "pytest"}),
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    assert json.loads(allowed.stdout)["permission"] == "allow"

    started = subprocess.run(
        ["python3", ".cursor/hooks/session_start.py"],
        input="{}",
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    assert started.returncode == 0, started.stderr
    context = json.loads(started.stdout)["additional_context"]
    assert "agent/main" in context
    assert "gpt-5-nano" in context
    assert "€20" in context
    assert "10" in context

    edited = subprocess.run(
        ["python3", ".cursor/hooks/after_file_edit.py"],
        input=json.dumps({"file_path": "/tmp/.env", "edits": []}),
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
        env={
            "PATH": "/usr/bin:/bin",
            "JIRA_ISSUE_KEY": "KAN-6",
            "GIT_BRANCH": "cursor/kan-6-autonomous-setup-dccb",
        },
    )
    assert edited.returncode == 0, edited.stderr
    assert "Do not commit secrets" in edited.stderr
    assert "KAN-6" in edited.stderr

    deterministic = subprocess.run(
        ["python3", ".cursor/hooks/stop.py"],
        input=json.dumps({"status": "completed"}),
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_BRANCH": "cursor/kan-6-autonomous-setup-dccb",
            "PR_STATE": "OPEN",
            "PR_URL": "https://github.com/CYBERNETIC-BIZ/CyberneticAgents/pull/1",
            "PR_TITLE": "[agent] Setup autonomous improvement system",
            "PR_BODY": "Linked ticket: KAN-6",
            "JIRA_ISSUE_KEY": "KAN-6",
        },
    )
    assert deterministic.returncode == 0, deterministic.stderr
    assert json.loads(deterministic.stdout) == {}
    assert "KAN-6" in deterministic.stderr
    assert "JIRA_API_TOKEN" in deterministic.stderr


def test_hooks_json_wires_the_four_events():
    config = json.loads((ROOT / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    assert config["version"] == 1
    for event in ("sessionStart", "beforeShellExecution", "afterFileEdit", "stop"):
        command = config["hooks"][event][0]["command"]
        script = ROOT / command.split()[-1]
        assert script.is_file()
    assert config["hooks"]["beforeShellExecution"][0]["failClosed"] is True
