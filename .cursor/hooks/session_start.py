#!/usr/bin/env python3
"""Cursor sessionStart hook: move the linked Jira issue to In Progress.

Cloud agents do not run sessionStart. The afterFileEdit hook performs the
same move on the first code edit in that environment.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Hooks run from a checkout that may not have the package installed.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cybernetic.jira_monitor import on_session_start, read_hook_input


def main() -> int:
    payload = read_hook_input(sys.stdin.read())
    response = on_session_start(payload)
    json.dump(response, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
