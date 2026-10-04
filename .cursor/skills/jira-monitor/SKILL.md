---
name: jira-monitor
description: Move the linked Jira issue as CyberneticAgents work starts, opens a pull request, and merges. Use when editing hooks or naming a branch for this repo.
---

# Jira monitor

Do not invent ticket keys. Resolution order is `JIRA_ISSUE_KEY`, then a branch slug like `kan-6` in `cursor/kan-6-...`, then an uppercase key in the pull request title or body. Model names such as `gpt-5` are ignored.

Site `https://lgbongiolo.atlassian.net`, cloud id `b908f08c-773a-4389-beab-787b98d0bc37`.

- Coding starts: status **In Progress**. `sessionStart` does this. Cloud agents skip `sessionStart`, so the first `afterFileEdit` does it instead.
- Pull request open at stop: status **In Review** and comment `In Review. Pull request: <url>`.
- Pull request merged: status **Done** (also `.github/workflows/jira-on-merge.yml`).

Hook scripts need `JIRA_EMAIL` and `JIRA_API_TOKEN` (or the `ATLASSIAN_` names). They cannot call the Cursor Atlassian connector. If the variables are missing, leave the issue unchanged and say so. Do not merge the pull request.
