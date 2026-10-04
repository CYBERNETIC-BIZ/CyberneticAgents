#!/usr/bin/env python3
"""Cursor beforeShellExecution hook.

Blocks pushes and merges into main or master, pull requests that do not
target agent/main, shell loops around live model APIs, and attempts to set
the spend-continue variable from the agent.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cybernetic.agent_guard import review_shell_command
from cybernetic.jira_monitor import read_hook_input


def _branch() -> str:
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


def main() -> int:
    payload = read_hook_input(sys.stdin.read())
    command = str(payload.get("command") or "")
    try:
        decision = review_shell_command(command, _branch())
    except Exception as exc:
        decision = {
            "permission": "allow",
            "agent_message": f"shell guard failed open: {exc}",
        }
    json.dump(decision, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
