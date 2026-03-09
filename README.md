# Frank

Frank is an AI agent that automates software development tasks end-to-end. It polls a task source (Slack or Monday.com) for pending tasks, uses Claude to implement them in code, validates the result, and ships a pull request — all without human intervention.

**Core principle: do not pass to AI what you can do with code.**

Branch naming, commit messages, PR titles and descriptions, test retries, git operations, API calls — these are all orchestrated by Frank's code. Claude is only invoked for the parts that genuinely require reasoning: reading a task description and writing the implementation.

---

## How It Works

```
Poll task source (every 30s)
  → Fetch pending tasks (Slack List or Monday.com board)
  → Generate git branch name
  → Create branch from main
  → Run Claude to implement the task
  → Run integration tests
      → If failing: ask Claude to fix (up to 3 retries)
  → Run linter
      → If failing: ask Claude to fix (up to 3 retries)
  → Commit and push
  → Open GitHub Pull Request
  → Mark task as done
  → Post reply/update with summary
```

---

## Requirements

- Python 3.10+
- [`claude`](https://github.com/anthropics/claude-code) CLI installed and authenticated
- [`gh`](https://cli.github.com/) GitHub CLI authenticated
- `git`
- Docker + Docker Compose (for integration tests and linting)
- A task source configured (Slack or Monday.com)

---

## Setup

1. Clone the repo and install dependencies:

   ```bash
   pip install requests
   ```

2. Configure your task source:

   **Slack:**
   ```bash
   export SLACK_TOKEN=xoxb-...
   ```
   Update the Slack List ID and column IDs in `frank/tasks/slack.py` to match your workspace.

   **Monday.com:**
   ```bash
   export MONDAY_TOKEN=your-api-token
   export MONDAY_BOARD_ID=your-board-id
   # Optional: defaults to "status"
   export MONDAY_STATUS_COLUMN_ID=status
   ```

---

## Running

```bash
# Using Slack (default)
python -m frank

# Using Monday.com
python -m frank --source monday

# Verbose output (raw stream-json)
python -m frank -v

# Custom retry limit
python -m frank --max-attempts 5
```

Frank will start polling every 30 seconds. Press `Ctrl+C` to stop.

Backward-compatible: `python frank.py` still works.

---

## Task Sources

Frank uses a `TaskSource` protocol so different backends are interchangeable:

| Source | Gets tasks from | Marks done by | Posts reply as |
|---|---|---|---|
| Slack | Slack List items (unchecked) | Checking done column | Thread reply |
| Monday.com | Board items with status "TO DO" | Setting status to "Done" | Item update (comment) |

---

## What Frank Does vs. What Claude Does

| Task | Done by |
|---|---|
| Poll task source | Frank (code) |
| Parse task descriptions | Frank (code) |
| Create git branches | Frank (code) |
| Implement the task | Claude |
| Fix failing tests | Claude |
| Fix linting errors | Claude |
| Generate branch/commit/PR names | Claude (Haiku) |
| Run tests and linting | Frank (code, Docker) |
| Commit, push, open PR | Frank (code, `gh` CLI) |
| Mark task done | Frank (code) |
| Reply with summary | Frank (code) |

The AI is used only where judgment is needed. Everything else is deterministic code.

---

## Architecture

Frank is a Python package (`frank/`) with clean module separation:

- **`frank/tasks/`** — Task source abstraction (`TaskSource` protocol) with Slack and Monday.com implementations
- **`frank/claude.py`** — Streams `claude` CLI output in real time, parses session IDs for conversation resumption
- **`frank/git.py`** — Branch creation, staging, commit, push, PR creation via `gh`
- **`frank/runners.py`** — Docker Compose test & lint runners with smart terminal output (last 4 lines shown)
- **`frank/formatter.py`** — Claude CLI stream-json log formatter
- **`frank/cli.py`** — CLI argument parsing and main orchestration loop with retry logic

---

## Environment Variables

| Variable | Source | Description |
|---|---|---|
| `SLACK_TOKEN` | Slack | Slack bot token (`xoxb-...`) |
| `MONDAY_TOKEN` | Monday | Monday.com API token |
| `MONDAY_BOARD_ID` | Monday | Board ID to poll for tasks |
| `MONDAY_STATUS_COLUMN_ID` | Monday | Status column ID (default: `status`) |

---

## Slack App Scopes

If using Slack, your app needs:
- `channels:join`, `channels:read`
- `chat:write`
- `lists:read`, `lists:write`
- `conversations.history:read`
