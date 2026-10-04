#!/usr/bin/env python3
"""Cursor afterFileEdit hook.

Warns on secret-shaped edits and marks the linked Jira issue In Progress
the first time code changes. sessionStart does not run for cloud agents, so
this is the coding-begins signal in that environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cybernetic.agent_guard import secret_edit_warning
from cybernetic.jira_monitor import on_file_edit_started, read_hook_input


def main() -> int:
    payload = read_hook_input(sys.stdin.read())
    edits = payload.get("edits")
    warning = secret_edit_warning(
        str(payload.get("file_path") or ""),
        edits if isinstance(edits, list) else [],
    )
    if warning:
        print(warning, file=sys.stderr)
    print(on_file_edit_started(), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
