---
name: run-cli
description: Run the CyberneticAgents CLI and pytest without API keys. Use when launching cybernetic.biz, showing Laya and Jev together, or running the test suite.
---

# Run the CLI

Install the test extra and stay on a `cursor/*` branch cut from `agent/main`. Do not commit to `main` or `master`.

```bash
python -m pip install -e ".[dev]"
cybernetic.biz --help
pytest
```

Show both decision providers for one piece of text:

```bash
CYBERNETIC_LAYA_FIXTURE=tests/fixtures/laya_response.json \
CYBERNETIC_JEV_FIXTURE=tests/fixtures/jev_response.json \
cybernetic.biz decide "We were billed twice. Please refund the duplicate."
```

The report prints `== Laya ==` and then `== Jev ==`. `tests/cli_harness.py` drives the same commands in-process. `pytest tests/test_cli_user_flow.py` is the user-flow check.

Do not export `CYBERNETIC_LIVE_CALLS` or `TYPESAFE_API_KEY` for ordinary runs. Live calls are opt-in and are skipped in CI. See the spend-guard skill.
