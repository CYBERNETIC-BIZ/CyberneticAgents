#!/usr/bin/env python3
"""Cursor stop hook.

When the agent finishes and a pull request is open, move the linked Jira
issue to In Review and comment with the pull request URL. A merged pull
request moves the issue to Done. This hook does not ask the agent to continue.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cybernetic.jira_monitor import on_stop, read_hook_input


def main() -> int:
    payload = read_hook_input(sys.stdin.read())
    message = on_stop(payload)
    print(message, file=sys.stderr)
    json.dump({}, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
