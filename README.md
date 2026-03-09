# Frank

Frank is an AI agent that automates software development tasks end-to-end. It polls a Slack board for pending tasks, uses Claude to implement them in code, validates the result, and ships a pull request — all without human intervention.

**Core principle: do not pass to AI what you can do with code.**

Branch naming, commit messages, PR titles and descriptions, test retries, git operations, Slack API calls — these are all orchestrated by Frank's code. Claude is only invoked for the parts that genuinely require reasoning: reading a task description and writing the implementation.

---

## How It Works

```
Poll Slack (every 30s)
  → Fetch pending tasks from Slack List
  → Generate git branch name
  → Create branch from main
  → Run Claude to implement the task
  → Run integration tests
      → If failing: ask Claude to fix (up to 3 retries)
  → Run linter
      → If failing: ask Claude to fix (up to 3 retries)
  → Commit and push
  → Open GitHub Pull Request
  → Mark Slack item as done
  → Reply to Slack thread with summary
```

---

## Requirements

- Python 3.10+
- [`claude`](https://github.com/anthropics/claude-code) CLI installed and authenticated
- [`gh`](https://cli.github.com/) GitHub CLI authenticated
- `git`
- Docker + Docker Compose (for integration tests and linting)
- A Slack app with the following scopes:
  - `channels:join`, `channels:read`
  - `chat:write`
  - `lists:read`, `lists:write`
  - `conversations.history:read`

---

## Setup

1. Clone the repo and install dependencies:

   ```bash
   pip install requests
   ```

2. Set your Slack token:

   ```bash
   export SLACK_TOKEN=xoxb-...
   ```

3. Update the Slack List ID and column IDs in `frank.py` to match your workspace:

   ```python
   SLACK_LIST_ID = "F09SH4T1B8Q"
   SLACK_DONE_COLUMN_ID = "Col00"
   ```

---

## Running

```bash
python frank.py
```

Frank will start polling Slack every 30 seconds. Press `Ctrl+C` to stop.

---

## What Frank Does vs. What Claude Does

| Task | Done by |
|---|---|
| Poll Slack for tasks | Frank (code) |
| Parse task descriptions | Frank (code) |
| Create git branches | Frank (code) |
| Implement the task | Claude |
| Fix failing tests | Claude |
| Fix linting errors | Claude |
| Generate branch/commit/PR names | Claude (Haiku) |
| Run tests and linting | Frank (code, Docker) |
| Commit, push, open PR | Frank (code, `gh` CLI) |
| Mark task done in Slack | Frank (code) |
| Reply to Slack thread | Frank (code) |

The AI is used only where judgment is needed. Everything else is deterministic code.

---

## Architecture

Frank is a single Python script (`frank.py`) with no external framework dependencies. Key sections:

- **Slack integration** — fetches tasks, marks them done, posts replies
- **Claude execution engine** — streams `claude` CLI output in real time, parses session IDs for conversation resumption
- **Git operations** — branch creation, staging, commit, push
- **GitHub PR creation** — via `gh` CLI
- **Test & lint runners** — Docker Compose, with smart terminal output (last 4 lines shown)
- **Retry loop** — up to 3 Claude-assisted fix attempts per failure

---

## Environment Variables

| Variable | Description |
|---|---|
| `SLACK_TOKEN` | Slack bot token (`xoxb-...`) |
