# Goals

## Product goal

> **Not written yet.** The owner (Luiz) will send the product goal later. Do not invent a product vision, roadmap, or success metric to fill this section.

## Tasks

### 1. Laya as a default provider next to Jev

Recorded from the owner, unchanged:

Implement [Laya](https://github.com/NandhaKishorM/laya) (non-autoregressive System 1 decision engine: typed choice, score, and yes/no over text in one forward pass) as a default provider alongside the existing Jev provider. The owner spelled it "jev". Keep Jev. Where the CLI can show both, show Laya and Jev for the same request, clearly labeled. Laya is a default provider, not a hidden optional. If a dependency, checkpoint, or network call cannot run in CI, gate the live call behind a clear skip and test the wiring with a fake or fixture. Do not add paid services or production credentials.

This checkout did not contain a Jev client. Jev is TypeSafe's hosted System One model (`jev-latest`, `POST /v1/systemone`). The CLI now runs that client next to Laya from `cybernetic.biz decide` and from the main menu. The six existing chat providers are unchanged.

Live calls are off by default, skipped in CI, and covered by fixtures in `tests/fixtures/`.
