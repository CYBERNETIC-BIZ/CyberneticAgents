"""Shell and edit guards for Cursor hooks.

Branch protection keeps work off main and master. The spend checks stop an
agent from looping a model API or from unlocking the live-run pause itself.
"""

import re
import shlex
from pathlib import Path
from typing import Dict, List, Optional

from cybernetic.spend import CONTINUE_ENV, LIVE_RUN_PAUSE

PROTECTED_BRANCHES = frozenset({"main", "master"})
_SEGMENT_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\n)\s*")
_LOOP = re.compile(r"(?:^|[\s;|&])(while|until|for|watch|xargs)(?:$|[\s;|&])")
_LIVE_API = re.compile(
    r"(api\.openai\.com|api\.typesafe\.ai|api\.anthropic\.com|"
    r"generativelanguage\.googleapis\.com|api\.x\.ai|openrouter\.ai|"
    r"CYBERNETIC_LIVE_CALLS|CYBERNETIC_LAYA_LIVE|CYBERNETIC_LIVE_OPENAI|"
    r"/v1/systemone|\bdecide\b)",
    re.IGNORECASE,
)
_CONTINUE_ASSIGN = re.compile(
    rf"(?:^|[\s;|&])(?:export\s+)?{CONTINUE_ENV}\s*=",
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api_key|secret|token|password)\s*=\s*['\"]?[A-Za-z0-9_\-]{12,}"
)
# Lowercase branch slugs that look like tickets but are model names in this CLI.
_BRANCH_SLUG_DENY = frozenset({
    "gpt",
    "claude",
    "gemini",
    "grok",
    "llama",
    "nemotron",
    "glm",
})


def command_segments(command: str) -> List[str]:
    return [part.strip() for part in _SEGMENT_SPLIT.split(command) if part.strip()]


def _argv(segment: str) -> List[str]:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return []
    while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
        tokens = tokens[1:]
    return tokens


def _executable(tokens: List[str]) -> str:
    if not tokens:
        return ""
    return Path(tokens[0]).name


def _option_value(tokens: List[str], name: str) -> Optional[str]:
    for index, token in enumerate(tokens):
        if token == name and index + 1 < len(tokens):
            return tokens[index + 1]
        if token.startswith(name + "="):
            return token.split("=", 1)[1]
    return None


def _ref_is_protected(ref: str) -> bool:
    ref = ref.removeprefix("+")
    if ":" in ref:
        ref = ref.split(":")[-1]
    ref = ref.removeprefix("refs/heads/")
    return ref in PROTECTED_BRANCHES


def _unquoted(command: str) -> str:
    """Drop quoted regions so a commit message is not treated as a shell loop."""
    return re.sub(r"""'[^']*'|"[^"]*"|'''[\s\S]*?'''""", " ", command)


def _spend_denial(command: str) -> Optional[str]:
    unquoted = _unquoted(command)
    if _CONTINUE_ASSIGN.search(unquoted):
        return (
            f"Refusing to set {CONTINUE_ENV} from the agent. "
            f"After every {LIVE_RUN_PAUSE} live runs the operator must export it "
            "to that run count in their own environment. Do not loop on an API."
        )
    if _LOOP.search(unquoted) and _LIVE_API.search(unquoted):
        return (
            "Refusing to loop a live model or API command. "
            f"Live runs pause every {LIVE_RUN_PAUSE} calls, and this repo's "
            "automated API spend must stay within €20 per month."
        )
    return None


def _deny_segment(segment: str, current_branch: str) -> Optional[str]:
    tokens = _argv(segment)
    executable = _executable(tokens)
    if executable == "gh" and len(tokens) >= 3 and tokens[1] == "pr" and tokens[2] == "merge":
        return "Refusing to merge a pull request. Only the owner merges agent/main into main."
    if executable == "gh" and len(tokens) >= 3 and tokens[1] == "pr" and tokens[2] == "create":
        base = _option_value(tokens, "--base")
        if base is None or base in PROTECTED_BRANCHES:
            return (
                "Pull requests must target agent/main. "
                "Refusing to open a pull request into main or master."
            )
    if executable == "git" and "push" in tokens[1:]:
        if current_branch in PROTECTED_BRANCHES:
            return "Refusing to push while the current branch is main or master."
        if "--all" in tokens or "--mirror" in tokens:
            return "Refusing git push --all or --mirror because it can update main or master."
        for token in tokens[1:]:
            if token.startswith("-") and not token.startswith("--"):
                continue
            if _ref_is_protected(token):
                return "Refusing to push main or master."
    if executable == "git" and "commit" in tokens[1:] and current_branch in PROTECTED_BRANCHES:
        return "Refusing to commit on main or master. Branch from agent/main."
    if (
        executable == "git"
        and "merge" in tokens[1:]
        and current_branch in PROTECTED_BRANCHES
    ):
        return "Refusing to merge into main or master."
    return None


def review_shell_command(command: str, current_branch: str) -> Dict[str, str]:
    """Return a Cursor beforeShellExecution permission decision."""
    spend_reason = _spend_denial(command)
    if spend_reason is not None:
        return {
            "permission": "deny",
            "user_message": spend_reason,
            "agent_message": spend_reason,
        }
    for segment in command_segments(command):
        reason = _deny_segment(segment, current_branch)
        if reason is not None:
            return {
                "permission": "deny",
                "user_message": reason,
                "agent_message": reason,
            }
    return {"permission": "allow"}


def secret_edit_warning(file_path: str, edits: Optional[List[dict]] = None) -> Optional[str]:
    """Warn when an edit looks like a secret. Hooks cannot block afterFileEdit."""
    name = Path(file_path).name
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return f"Edited {name}. Do not commit secrets or production credentials."
    if name.endswith(".pem") or (name.endswith(".key") and name != "example.key"):
        return f"Edited {name}. Do not commit private keys."
    for edit in edits or []:
        new_string = edit.get("new_string") if isinstance(edit, dict) else None
        if isinstance(new_string, str) and _SECRET_ASSIGNMENT.search(new_string):
            if name == ".env.example":
                continue
            return (
                f"Edit to {name} assigns what looks like a credential. "
                "Do not commit production credentials."
            )
    return None


def branch_slug_denied(project: str) -> bool:
    """True when a lowercase branch token is a model name, not a Jira key."""
    return project.lower() in _BRANCH_SLUG_DENY
