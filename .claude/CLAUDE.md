# Frank - Claude CLI Task Orchestrator

## Overview
Frank orchestrates Claude CLI agent tasks. It polls task sources (Slack or Monday.com) for pending work, uses Claude to implement them, validates the result, and ships a pull request.

## Package Structure
```
frank/
  colors.py          # ANSI color utilities (COLORS dict, c() helper)
  formatter.py       # Stream-json log formatter (format_stream_line + helpers)
  claude.py          # Claude CLI execution (execute_claude, main_prompt)
  git.py             # Git/GitHub operations (branch, commit, push, PR, Haiku generation)
  runners.py         # Docker-based integration tests & lint runner
  cli.py             # CLI entry point with argparse (main(), --source flag)
  __main__.py        # Polling loop entry point (python -m frank)
  tasks/
    base.py          # Task dataclass + TaskSource Protocol
    slack.py         # SlackTaskSource (env: SLACK_TOKEN)
    monday.py        # MondayTaskSource (env: MONDAY_TOKEN, MONDAY_BOARD_ID)
    __init__.py      # get_task_source() factory
```
- `frank.py` - Backward-compatible shim (delegates to frank package)
- `docs/frank-claude-cli-json/` - Reference JSON examples for stream-json events

## Stream-JSON Event Types (from `claude --output-format stream-json`)

All JSON examples are in `docs/frank-claude-cli-json/`.

### Core Types
| Type | Description | Formatter |
|------|-------------|-----------|
| `system` (subtype=`init`) | Session start: model, tools, agents, plugins, version | `_format_system` |
| `system` (subtype=`task_started`) | Sub-agent/task starts execution | `_format_system` |
| `assistant` | Claude response: thinking, text, tool_use blocks | `_format_assistant` |
| `user` | Tool results, sub-agent prompts, Agent completion results | `_format_user` |
| `result` | Session end: success/error, cost, duration, turns, denials | `_format_result` |
| `rate_limit_event` | Rate limit status (only shown if not "allowed") | `_format_rate_limit` |

### Sub-Agent Pattern
When Claude uses the `Agent` tool, a sub-agent context is created:
1. `assistant` with `tool_use` block where `name="Agent"` (contains `subagent_type`, `description`, `prompt`)
2. `system` with `subtype="task_started"` (contains `task_id`, `task_type="local_agent"`)
3. Multiple `assistant`/`user` pairs with `parent_tool_use_id` set (sub-agent's own tool calls)
4. `user` with `tool_use_result.status` field (sub-agent completion: `"completed"`)

### Key Fields
- `parent_tool_use_id`: Non-null on messages belonging to a sub-agent context. Used to indent sub-agent output.
- `tool_use_result.status`: Present on Agent tool results (`"completed"`). Distinguishes from file edit results.
- `tool_use_result.filePath` + `structuredPatch`: Present on file edit results (shows +/- line counts).
- `caller.type`: Present on tool_use blocks (always `"direct"` so far).

### Display Conventions
- Sub-agent messages are indented with `"  "` prefix
- Color coding: cyan=session, magenta=sub-agent, green=output, yellow=tool, blue=tool-result, red=error, dim=previews
- `[sub-agent]`, `[sub-tool]`, `[sub-result]` labels for sub-agent context
- `[sub-agent done]` for Agent tool completion

### JSON Examples (`docs/frank-claude-cli-json/`)
- `type_system.json` / `type_system_init_v2.json` - system:init (v2 adds agents, plugins, version, skills, slash_commands, fast_mode_state)
- `type_system_task_started.json` - system:task_started (sub-agent start)
- `type_assistant_1.json` - thinking block
- `type_assistant_2.json` - tool_use block (Edit)
- `type_assistant_3.json` - text block (final answer)
- `type_assistant_agent_tool.json` - Agent tool_use (spawns sub-agent)
- `type_assistant_subagent.json` - assistant message inside sub-agent (has parent_tool_use_id)
- `type_user.json` - tool result with filePath + structuredPatch
- `type_user_subagent_prompt.json` - user message inside sub-agent (initial prompt)
- `type_user_agent_result.json` - Agent tool completion (tool_use_result.status)
- `type_result.json` / `type_result_v2.json` - session result (v2 adds duration_api_ms, permission_denials, fast_mode_state, stop_reason)
- `type_rate_limit_event.json` - rate limit event
