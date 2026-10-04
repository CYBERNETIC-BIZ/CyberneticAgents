"""In-process user-flow harness for the cybernetic.biz CLI.

Live Laya and Jev calls stay off. Pass fixture files to see both providers
answer the same text without API keys, checkpoints, or network.
"""

import os
from pathlib import Path
from typing import Optional, Sequence

from typer.testing import CliRunner

from cybernetic.cli.app import app

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class CliHarness:
    """Drive Typer commands the way a terminal user would."""

    def __init__(
        self,
        *,
        laya_fixture: Optional[Path] = None,
        jev_fixture: Optional[Path] = None,
        extra_env: Optional[dict] = None,
    ) -> None:
        self.runner = CliRunner()
        self.env = os.environ.copy()
        self.env["CYBERNETIC_SKIP_LIVE_DECISIONS"] = "1"
        self.env["TYPESAFE_API_KEY"] = ""
        self.env.pop("CYBERNETIC_LIVE_CALLS", None)
        self.env.pop("CYBERNETIC_LAYA_FIXTURE", None)
        self.env.pop("CYBERNETIC_JEV_FIXTURE", None)
        if laya_fixture is not None:
            self.env["CYBERNETIC_LAYA_FIXTURE"] = str(laya_fixture)
        if jev_fixture is not None:
            self.env["CYBERNETIC_JEV_FIXTURE"] = str(jev_fixture)
        if extra_env:
            self.env.update(extra_env)

    def invoke(self, args: Sequence[str]):
        """Run ``cybernetic.biz`` with ``args`` and return the CliRunner result."""
        return self.runner.invoke(app, list(args), env=self.env)


def default_decision_harness() -> CliHarness:
    """Harness whose ``decide`` command prints fixture answers from both models."""
    return CliHarness(
        laya_fixture=FIXTURES / "laya_response.json",
        jev_fixture=FIXTURES / "jev_response.json",
    )
