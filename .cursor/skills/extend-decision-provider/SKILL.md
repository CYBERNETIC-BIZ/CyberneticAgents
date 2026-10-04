---
name: extend-decision-provider
description: Add or change a System One decision provider (Laya, Jev, or a new one) in CyberneticAgents. Use when editing cybernetic/decisions, the decide command, or provider fixtures.
---

# Extend a decision provider

Laya and Jev are the default decision providers. They are not chat models. Leave `cybernetic.llm` and its six chat providers in place.

- Provider classes live in `cybernetic/decisions/` and expose `name` plus `evaluate(state, questions) -> ProviderOutcome`.
- `default_providers()` returns Laya then Jev. A new default has to stay in that function and in the `decide` report.
- Questions are choice, score, or noul objects. The built-in set in `questions.py` is only a stand-in until `GOALS.md` has a product goal.
- Fixture files under `tests/fixtures/` must answer the same question ids so tests can show both outputs with no network.
- A live path checks `cybernetic.spend.live_calls_blocked_reason()` and `get_guard().authorize(...)` before any checkpoint download or HTTP call. If the call cannot run in CI, skip with a reason that says no request was sent.
- Do not add API keys, paid SDK credentials, or a dependency CI cannot import. Laya stays an optional extra (`laya` in `pyproject.toml`) because it pulls in torch.

User-facing entry points are `cybernetic.biz decide` and the menu item "Decide with Laya and Jev".
