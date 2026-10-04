---
name: spend-guard
description: Enforce the CyberneticAgents live-call spend cap. Use before any OpenAI, Jev, or Laya call, and when a test or hook might loop an API.
---

# Spend guard

Automated model calls stay within €20 per UTC month. Do not loop on any API. Tests stay on fixtures unless a person opts in.

The reserve uses `gpt-5-nano` at $0.05 / 1M input and $0.40 / 1M output, Jev at $0.042 / 1M input and $0 output, and 1 USD = 1 EUR. Details and the pause count are in `AGENTS.md` and `cybernetic/spend.py`.

- Call `SpendGuard.authorize` before every live request. A refusal means do not send it.
- OpenAI live calls from tests must use `gpt-5-nano` only.
- One process may reserve at most €1. The month may reserve at most €20.
- Every 10 live runs, stop. Continue only when `CYBERNETIC_SPEND_CONTINUE` equals that count. Do not export that variable from the agent, and do not wrap a live call in a shell loop.
- `CYBERNETIC_LIVE_CALLS=1` opts in. `CI=true` and `CYBERNETIC_SKIP_LIVE_DECISIONS=1` skip. CI ignores the opt-in.
- Do not commit `.cybernetic/spend-ledger.json` or any API key.
