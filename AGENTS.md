# Agents

CyberneticAgents is a Python CLI (`cybernetic.biz`). The product goal is not written yet. Read `GOALS.md` and do not invent a vision, roadmap, or success metric.

The owner is Luiz. Only the owner merges `agent/main` into `main`.

## Branch rules

- Do not commit, push, or open a pull request into `main` or `master`.
- Do not merge anything.
- `agent/main` is the long-lived integration branch, created from `main`. Creating it is not a merge.
- Do the work on a new branch cut from `agent/main`: `cursor/<descriptive-name>-dccb`.
- Open the pull request into `agent/main`.

The `beforeShellExecution` hook denies pushes and commits on `main`/`master`, pull requests whose base is not `agent/main`, and `gh pr merge`.

## Spend rule

Automated model calls in this repo must stay within **€20 per calendar month (UTC)**. Do not loop on any API.

Tests do not call live APIs unless someone opts in. CI skips live calls even if the opt-in variable is set. Fixtures cover Laya and Jev wiring.

| Rule | Value |
| --- | --- |
| Cheap OpenAI model for a live test | `gpt-5-nano` |
| OpenAI price used for the reserve | $0.05 / 1M input tokens, $0.40 / 1M output tokens |
| Jev price used for the reserve | $0.042 / 1M input tokens, $0 output (`jev-latest`) |
| FX assumption | 1 USD = 1 EUR |
| Per-run cap | €1 (`PER_RUN_CAP_EUR` in `cybernetic/spend.py`) |
| Monthly cap | €20 |
| Live-run pause | every 10 live runs (`LIVE_RUN_PAUSE`) |

Prices were taken from OpenAI's gpt-5-nano model page and TypeSafe's published Jev input rate, checked 2026-10-04. Jev token reserves use `len(text) // 4` plus 512 overhead tokens (measured overhead is about 260). Laya is local, so a live forward pass reserves €0 and still counts as one live run.

Before each live call, `SpendGuard.authorize` checks the opt-in, the CI skip, the model (OpenAI must be `gpt-5-nano`), the pause, the €1 run cap, and the €20 month cap. A refused call is not sent.

After every 10 live runs the next call stops until the operator sets `CYBERNETIC_SPEND_CONTINUE` to that exact count (`10`, then `20`, and so on). One value unlocks only the next batch. Agents must not set `CYBERNETIC_SPEND_CONTINUE`; the shell hook denies that assignment. Do not put a live call inside `while`, `for`, `until`, `watch`, or `xargs`.

Opt in with `CYBERNETIC_LIVE_CALLS=1`. `CYBERNETIC_SKIP_LIVE_DECISIONS=1` or `CI=true` forces a skip. The ledger is `.cybernetic/spend-ledger.json` (gitignored). Override it with `CYBERNETIC_SPEND_LEDGER` in tests.

No production credentials belong in the repo.

## CLI

```bash
python -m pip install -e ".[dev]"
cybernetic.biz --help
cybernetic.biz decide "Text to evaluate"
cybernetic.biz dashboard
cybernetic.biz schedule AGENT_ID --daily 09:30
```

`decide` is the user flow that runs Laya and Jev on the same text and prints them in that order, labeled `== Laya ==` and `== Jev ==`. The built-in questions are a choice, a score, and a yes/no. They are not a product goal. Pass `--questions file.json` to replace them.

Default `decide` does not call a live model. To see fixture output:

```bash
CYBERNETIC_LAYA_FIXTURE=tests/fixtures/laya_response.json \
CYBERNETIC_JEV_FIXTURE=tests/fixtures/jev_response.json \
cybernetic.biz decide "We were billed twice. Please refund the duplicate."
```

To make a live call, install the optional extra when you want Laya checkpoints (`pip install -e ".[laya]"`), export `CYBERNETIC_LIVE_CALLS=1`, and export `TYPESAFE_API_KEY` for Jev. Leave the key unset to skip Jev. Laya downloads checkpoints only on that opted-in path.

Laya and Jev are decision engines, not chat models. The existing chat providers (OpenAI, Anthropic, Google, xAI, OpenRouter, Ollama) stay on the research path. Jev was not previously wired in this CLI; the client speaks TypeSafe `POST /v1/systemone` for `jev-latest`.

The interactive menu item is "Decide with Laya and Jev".

## Tests

```bash
pytest
```

No secrets are required. The suite sets `CYBERNETIC_SKIP_LIVE_DECISIONS=1`, points the spend ledger at a temp file, and uses fixtures or `httpx.MockTransport` for provider wiring.

`tests/cli_harness.py` drives the Typer app in-process. `tests/test_cli_user_flow.py` is the user-flow test: help, `decide` with both labeled outputs, a custom question file, an empty dashboard, and `schedule`.

## Jira

Site: `https://lgbongiolo.atlassian.net`. Cloud id: `b908f08c-773a-4389-beab-787b98d0bc37`.

Find the linked issue from `JIRA_ISSUE_KEY`, a branch slug such as `cursor/kan-6-...`, or an uppercase key in the pull request title or body. Do not invent keys. Model names such as `gpt-5` are not keys.

| When | Status | Comment |
| --- | --- | --- |
| Coding starts (`sessionStart`, or the first `afterFileEdit` on cloud agents) | In Progress | none |
| Agent stops and a pull request is open | In Review | `In Review. Pull request: <url>` |
| Pull request merged | Done | none |

`sessionStart` does not run for Cursor cloud agents. `afterFileEdit` performs the In Progress move once per checkout.

Hook scripts call the Jira REST API. They cannot use the Cursor Atlassian connector. Set `JIRA_EMAIL` (or `ATLASSIAN_EMAIL`) and `JIRA_API_TOKEN` (or `ATLASSIAN_API_TOKEN`). Without those, the hook prints the skip and leaves the issue unchanged. `.github/workflows/jira-on-merge.yml` runs the same move to Done and needs those values as repository secrets.

## Hooks and skills

Project hooks live in `.cursor/hooks.json`: `sessionStart`, `beforeShellExecution`, `afterFileEdit`, and `stop`.

Skills:

- `.cursor/skills/run-cli/SKILL.md`
- `.cursor/skills/extend-decision-provider/SKILL.md`
- `.cursor/skills/spend-guard/SKILL.md`
- `.cursor/skills/jira-monitor/SKILL.md`
