import argparse
import json
import os
import re
import subprocess
import sys

from collections import deque
from typing import List

import requests

COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "red": "\033[31m",
}
SLACK_LIST_ID = "F09SH4T1B8Q"
SLACK_DONE_COLUMN_ID = "Col00"


def c(color: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def format_stream_line(raw_line: str) -> str | None:
    """Parse a stream-json line and return a human-readable message, or None to skip."""
    line = raw_line.strip()
    if not line:
        return None

    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return line

    if not isinstance(data, dict):
        return line

    event_type = data.get("type")

    if event_type == "system":
        return _format_system(data)

    if event_type == "assistant":
        return _format_assistant(data)

    if event_type == "user":
        return _format_user(data)

    if event_type == "result":
        return _format_result(data)

    if event_type == "rate_limit_event":
        return _format_rate_limit(data)

    return None


def _format_system(data: dict) -> str | None:
    subtype = data.get("subtype", "")
    if subtype == "init":
        model = data.get("model", "?")
        tools = data.get("tools", [])
        mcp_servers = data.get("mcp_servers", [])
        connected = [s["name"] for s in mcp_servers if s.get("status") == "connected"]
        agents = data.get("agents", [])
        plugins = data.get("plugins", [])
        version = data.get("claude_code_version", "")
        parts = [
            c("cyan", f"[session] ") + f"model={c('bold', model)}",
            f"  tools: {len(tools)}",
        ]
        if version:
            parts.append(f"  version: {version}")
        if connected:
            parts.append(f"  mcp: {', '.join(connected)}")
        if agents:
            parts.append(f"  agents: {', '.join(agents)}")
        if plugins:
            plugin_names = [p.get("name", "?") for p in plugins]
            parts.append(f"  plugins: {', '.join(plugin_names)}")
        return "\n".join(parts)
    if subtype == "task_started":
        desc = data.get("description", "")
        task_type = data.get("task_type", "")
        task_id = data.get("task_id", "")
        parts = [c("magenta", f"[sub-agent] ") + c("bold", desc)]
        if task_type:
            parts[0] += f"  {c('dim', task_type)}"
        return parts[0]
    return None


def _format_assistant(data: dict) -> str | None:
    message = data.get("message", {})
    content_blocks = message.get("content", [])
    is_subagent = data.get("parent_tool_use_id") is not None
    indent = "  " if is_subagent else ""
    parts = []
    for block in content_blocks:
        block_type = block.get("type")

        if block_type == "thinking":
            thinking = block.get("thinking", "")
            preview = thinking[:100].replace("\n", " ")
            if len(thinking) > 100:
                preview += "..."
            parts.append(indent + c("dim", f"[thinking] {preview}"))

        elif block_type == "text":
            text = block.get("text", "").strip()
            if text:
                prefix = c("magenta", "[sub-agent] ") if is_subagent else c("green", "[output] ")
                parts.append(indent + prefix + text)

        elif block_type == "tool_use":
            tool_name = block.get("name", "?")
            tool_input = block.get("input", {})
            summary = _summarize_tool_input(tool_name, tool_input)
            prefix = indent + (c("magenta", f"[sub-tool] ") if is_subagent else c("yellow", f"[tool] "))
            parts.append(prefix + f"{tool_name}" + (f" {summary}" if summary else ""))

    if parts:
        return "\n".join(parts)
    return None


def _format_user(data: dict) -> str | None:
    is_subagent = data.get("parent_tool_use_id") is not None
    indent = "  " if is_subagent else ""
    result_label = c("magenta", "[sub-result] ") if is_subagent else c("blue", "[tool result] ")

    tool_result = data.get("tool_use_result")
    if not tool_result or not isinstance(tool_result, dict):
        message = data.get("message", {})
        if not isinstance(message, dict):
            return None
        for block in message.get("content", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result":
                content = block.get("content", "")
                if isinstance(content, list):
                    texts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
                    content = " ".join(texts)
                if isinstance(content, str) and content:
                    preview = content[:150].replace("\n", " ")
                    if len(content) > 150:
                        preview += "..."
                    return indent + result_label + c("dim", preview)
        return None

    # Agent tool result (sub-agent completed)
    status = tool_result.get("status")
    if status:
        result_text = str(tool_result.get("result", ""))
        preview = result_text[:150].replace("\n", " ")
        if len(result_text) > 150:
            preview += "..."
        return c("magenta", f"[sub-agent done] ") + c("dim", f"status={status}") + (f" {c('dim', preview)}" if preview else "")

    file_path = tool_result.get("filePath", "")
    patch = tool_result.get("structuredPatch", [])
    if file_path and patch:
        added = sum(1 for p in patch for l in p.get("lines", []) if l.startswith("+"))
        removed = sum(1 for p in patch for l in p.get("lines", []) if l.startswith("-"))
        parts = [indent + result_label + c("dim", file_path)]
        if added or removed:
            parts[0] += f"  {c('green', f'+{added}')} {c('red', f'-{removed}')}"
        return parts[0]

    if file_path:
        return indent + result_label + c("dim", file_path)

    message = data.get("message", {})
    if not isinstance(message, dict):
        return None
    for block in message.get("content", []):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            content = block.get("content", "")
            if isinstance(content, list):
                texts = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
                content = " ".join(texts)
            if isinstance(content, str) and content:
                preview = content[:150].replace("\n", " ")
                if len(content) > 150:
                    preview += "..."
                return indent + result_label + c("dim", preview)
    return None


def _format_result(data: dict) -> str:
    is_error = data.get("is_error", False)
    cost = data.get("total_cost_usd")
    duration_ms = data.get("duration_ms")
    duration_api_ms = data.get("duration_api_ms")
    num_turns = data.get("num_turns")
    result_text = data.get("result", "")

    status = c("red", "FAILED") if is_error else c("green", "SUCCESS")
    info_parts = [f"{status}"]
    if num_turns is not None:
        info_parts.append(f"turns: {num_turns}")
    if duration_ms is not None:
        info_parts.append(f"time: {duration_ms / 1000:.1f}s")
        if duration_api_ms is not None:
            info_parts.append(f"api: {duration_api_ms / 1000:.1f}s")
    if cost is not None:
        info_parts.append(f"cost: ${cost:.4f}")

    model_usage = data.get("modelUsage", {})
    if model_usage:
        models = ", ".join(model_usage.keys())
        info_parts.append(f"models: {models}")

    permission_denials = data.get("permission_denials", [])
    if permission_denials:
        info_parts.append(f"denials: {len(permission_denials)}")

    header = c("bold", "[result] ") + " | ".join(info_parts)

    if result_text:
        return f"{header}\n{result_text}"
    return header


def _format_rate_limit(data: dict) -> str | None:
    info = data.get("rate_limit_info", {})
    status = info.get("status", "")
    if status != "allowed":
        return c("red", f"[rate limit] {status}")
    return None


def _summarize_tool_input(tool_name: str, tool_input: dict) -> str:
    """Return a short summary of tool input for human readability."""
    if tool_name in ("Read", "Write"):
        return c("dim", tool_input.get("file_path", ""))
    if tool_name == "Edit":
        fp = tool_input.get("file_path", "")
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        preview = fp
        if old:
            old_preview = old[:40].replace("\n", "\\n")
            new_preview = new[:40].replace("\n", "\\n")
            preview += f'  "{old_preview}" -> "{new_preview}"'
        return c("dim", preview)
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        if len(cmd) > 120:
            cmd = cmd[:120] + "..."
        return c("dim", cmd)
    if tool_name in ("Glob", "Grep"):
        pattern = tool_input.get("pattern", "")
        return c("dim", pattern)
    if tool_name == "ToolSearch":
        query = tool_input.get("query", "")
        return c("dim", query)
    if tool_name in ("Task", "Agent"):
        desc = tool_input.get("description", "")
        subagent_type = tool_input.get("subagent_type", "")
        if subagent_type:
            return c("dim", f"[{subagent_type}] {desc}")
        return c("dim", desc)
    # Fallback: show first key=value pairs
    items = list(tool_input.items())[:2]
    if items:
        return c("dim", ", ".join(f"{k}={v}" for k, v in items if isinstance(v, str)))
    return ""


def _join_channel(channel_id: str, token: str, headers: dict) -> None:
    """Join a Slack channel so the bot can read messages."""
    response = requests.post(
        "https://slack.com/api/conversations.join",
        headers=headers,
        json={"channel": channel_id},
    )
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API error (conversations.join): {data.get('error', 'unknown')}")


def get_thread_first_message(channel_id: str, thread_ts: str) -> str:
    """Fetch the first message of a Slack thread to get the full task description."""
    token = os.getenv("SLACK_TOKEN")
    url = "https://slack.com/api/conversations.replies"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    params = {
        "channel": channel_id,
        "ts": thread_ts,
        "limit": 1,
        "inclusive": True,
    }

    response = requests.get(url, headers=headers, params=params)
    data = response.json()

    if not data.get("ok") and data.get("error") == "not_in_channel":
        print(f"[frank] Bot not in channel {channel_id}, joining...")
        _join_channel(channel_id, token, headers)
        response = requests.get(url, headers=headers, params=params)
        data = response.json()

    if not data.get("ok"):
        raise RuntimeError(f"Slack API error (conversations.replies): {data.get('error', 'unknown')}")

    messages = data.get("messages", [])
    if messages:
        return messages[0].get("text")
    return None


def get_tasks_in_slack() -> List[dict]:
    """Fetch items from a Slack list and return pending tasks with thread info."""
    token = os.getenv("SLACK_TOKEN")
    list_id = SLACK_LIST_ID
    task_column_id = "Col09R7BY1SAK"
    message_column_id = "Col09V53TL7JB"
    done_column_id = SLACK_DONE_COLUMN_ID
    url = "https://slack.com/api/slackLists.items.list"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    items_list = []
    cursor = None

    while True:
        payload = {"list_id": list_id, "limit": 100}
        if cursor:
            payload["cursor"] = cursor

        response = requests.post(url, headers=headers, json=payload)
        data = response.json()

        if not data.get("ok"):
            error = data.get("error", "unknown")
            print(f"Slack API error: {error}")
            sys.exit(1)

        for item in data.get("items", []):
            item_id = item.get("id")
            raw_fields = item.get("fields", [])
            if isinstance(raw_fields, list):
                fields = {f["column_id"]: f for f in raw_fields if "column_id" in f}
            else:
                fields = raw_fields

            # Skip items already marked as done
            done_field = fields.get(done_column_id, {})
            if done_field.get("checkbox") is True:
                continue

            # Extract task text
            task_field = fields.get(task_column_id, {})
            text = task_field.get("text")
            if not text:
                continue

            # Extract message thread info
            message_field = fields.get(message_column_id, {})
            messages = message_field.get("message", [])
            channel_id = None
            thread_ts = None
            if messages:
                channel_id = messages[0].get("channel_id")
                raw_thread_ts = messages[0].get("thread_ts", "")
                if raw_thread_ts and raw_thread_ts != "0000000000.000000":
                    thread_ts = raw_thread_ts
                else:
                    thread_ts = messages[0].get("ts")

            # Fetch full message from thread (the list column truncates it)
            if channel_id and thread_ts:
                full_text = get_thread_first_message(channel_id, thread_ts)
                if full_text:
                    text = full_text

            items_list.append(
                {
                    "id": item_id,
                    "text": text,
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                }
            )

        response_metadata = data.get("response_metadata", {})
        cursor = response_metadata.get("next_cursor")
        if not cursor:
            break

    return items_list


def mark_slack_item_done(item_id: str) -> bool:
    """Mark a checkbox column as true for a Slack list item."""
    token = os.getenv("SLACK_TOKEN")
    list_id = SLACK_LIST_ID
    column_id = SLACK_DONE_COLUMN_ID
    url = "https://slack.com/api/slackLists.items.update"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    payload = {
        "list_id": list_id,
        "cells": [
            {
                "row_id": item_id,
                "column_id": column_id,
                "checkbox": True,
            }
        ],
    }

    response = requests.post(url, headers=headers, json=payload)
    data = response.json()

    if not data.get("ok"):
        print(f"Slack API error: {data.get('error', 'unknown')}")
        return False

    return True


def reply_to_slack_thread(channel_id: str, thread_ts: str, text: str = "Done") -> bool:
    """Post a reply to a Slack message thread."""
    token = os.getenv("SLACK_TOKEN")
    url = "https://slack.com/api/chat.postMessage"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    payload = {
        "channel": channel_id,
        "thread_ts": thread_ts,
        "text": text,
    }

    response = requests.post(url, headers=headers, json=payload)
    data = response.json()

    if not data.get("ok"):
        print(f"Slack API error: {data.get('error', 'unknown')}")
        return False

    return True


def generate_task_description(task_text: str) -> str:
    """Get the git diff and call Claude Haiku to generate a task description."""
    print(c("cyan", "[frank] Generating task description..."))

    diff_result = subprocess.run(
        ["git", "diff", "HEAD"],
        capture_output=True,
        text=True,
    )
    diff = diff_result.stdout.strip()

    if not diff:
        return "Feito."

    prompt = (
        f"You are summarizing code changes for a Slack thread reply.\n"
        f"The original task was: {task_text}\n\n"
        f"Here is the git diff:\n{diff}\n\n"
        f"Write a short description (2-4 sentences) in Brazilian Portuguese (pt-BR) of what was done. "
        f"Be concise and technical. Do not use markdown. "
        f"Start with 'Feito.' followed by the description."
    )

    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        "claude-haiku-4-5-20251001",
        "--permission-mode",
        "acceptEdits",
        "--output-format",
        "text",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    description = result.stdout.strip()

    if not description or result.returncode != 0:
        print(c("yellow", f"[frank] Failed to generate description (exit={result.returncode}), using fallback."))
        if result.stderr.strip():
            print(c("dim", f"[frank] stderr: {result.stderr.strip()[:300]}"))
        return "Feito."

    return description


def generate_branch_name(task_text: str) -> str:
    """Use Claude Haiku to generate a clean git branch name from task text."""
    print(c("cyan", "[frank] Generating branch name..."))
    prompt = (
        f"Generate a short git branch name for this task:\n{task_text}\n\n"
        f"Rules:\n"
        f"- Use kebab-case (lowercase with hyphens)\n"
        f"- Prefix with 'frank/'\n"
        f"- Max 50 chars total\n"
        f"- Only lowercase letters, numbers, hyphens, and one forward slash after 'frank'\n"
        f"- Return ONLY the branch name, nothing else\n"
        f"- No quotes, no backticks, no explanation"
    )
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        "claude-haiku-4-5-20251001",
        "--permission-mode",
        "acceptEdits",
        "--output-format",
        "text",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    branch = result.stdout.strip().strip("`").strip('"').strip("'")

    if not branch or result.returncode != 0 or not branch.startswith("frank/"):
        sanitized = re.sub(r"[^a-z0-9]+", "-", task_text.lower()[:40]).strip("-")
        return f"frank/{sanitized}"
    return branch


def create_branch(branch_name: str) -> bool:
    """Create and checkout a git branch from main, or switch to it if it already exists."""
    subprocess.run(["git", "checkout", "main"], capture_output=True, text=True)
    subprocess.run(["git", "pull", "--ff-only"], capture_output=True, text=True)

    result = subprocess.run(
        ["git", "checkout", "-b", branch_name],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Branch may already exist, try switching to it
        result = subprocess.run(
            ["git", "checkout", branch_name],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(c("red", f"[frank] Failed to create/switch branch: {result.stderr.strip()}"))
            return False
        print(c("green", f"[frank] Switched to existing branch: {branch_name}"))
        return True
    print(c("green", f"[frank] Created branch: {branch_name}"))
    return True


def generate_commit_message(task_text: str) -> str:
    """Use Claude Haiku to generate a conventional commit message from staged changes."""
    print(c("cyan", "[frank] Generating commit message..."))
    diff_result = subprocess.run(
        ["git", "diff", "--staged"],
        capture_output=True,
        text=True,
    )
    diff = diff_result.stdout.strip()
    if not diff:
        return f"feat: {task_text[:60]}"

    prompt = (
        f"Generate a conventional commit message for these changes.\n"
        f"Task: {task_text}\n\n"
        f"Git diff:\n{diff[:8000]}\n\n"
        f"Rules:\n"
        f"- Use conventional commits format (feat:, fix:, chore:, etc.)\n"
        f"- First line max 72 chars\n"
        f"- Optionally add a blank line and a short body (2-3 lines)\n"
        f"- Return ONLY the commit message, nothing else\n"
        f"- No quotes, no backticks, no explanation"
    )
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        "claude-haiku-4-5-20251001",
        "--permission-mode",
        "acceptEdits",
        "--output-format",
        "text",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    msg = result.stdout.strip()
    if not msg or result.returncode != 0:
        return f"feat: {task_text[:60]}"
    return msg


def commit_and_push(branch_name: str, task_text: str) -> bool:
    """Stage all changes, generate commit message, commit, and push."""
    print(c("cyan", "[frank] Committing and pushing changes..."))

    subprocess.run(["git", "add", "."], capture_output=True, text=True)

    # Check if there are staged changes
    status = subprocess.run(
        ["git", "diff", "--staged", "--quiet"],
        capture_output=True,
        text=True,
    )
    if status.returncode == 0:
        print(c("yellow", "[frank] No changes to commit."))
        return False

    commit_msg = generate_commit_message(task_text)
    result = subprocess.run(
        ["git", "commit", "-m", commit_msg],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(c("red", f"[frank] Failed to commit: {result.stderr.strip()}"))
        return False
    print(c("green", f"[frank] Committed: {commit_msg.split(chr(10))[0]}"))

    result = subprocess.run(
        ["git", "push", "-u", "origin", branch_name],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(c("red", f"[frank] Failed to push: {result.stderr.strip()}"))
        return False
    print(c("green", f"[frank] Pushed to origin/{branch_name}"))
    return True


def create_pull_request(task_text: str) -> str | None:
    """Create a GitHub PR using gh CLI. Returns the PR URL or None."""
    print(c("cyan", "[frank] Creating pull request..."))

    pr_title = _generate_pr_title(task_text)
    pr_body = _generate_pr_description(task_text)

    result = subprocess.run(
        ["gh", "pr", "create", "--title", pr_title, "--body", pr_body],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(c("red", f"[frank] Failed to create PR: {result.stderr.strip()}"))
        return None

    pr_url = result.stdout.strip()
    print(c("green", f"[frank] Created PR: {pr_url}"))
    return pr_url


def _generate_pr_title(task_text: str) -> str:
    """Use Claude Haiku to generate a short PR title."""
    prompt = (
        f"Generate a short GitHub pull request title for this task:\n{task_text}\n\n"
        f"Rules:\n"
        f"- Max 70 characters\n"
        f"- Clear and descriptive\n"
        f"- Return ONLY the title, nothing else\n"
        f"- No quotes, no backticks"
    )
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        "claude-haiku-4-5-20251001",
        "--permission-mode",
        "acceptEdits",
        "--output-format",
        "text",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    title = result.stdout.strip().strip('"').strip("'")
    if not title or result.returncode != 0:
        return task_text[:70]
    return title[:70]


def _generate_pr_description(task_text: str) -> str:
    """Use Claude Haiku to generate a PR description from the diff against main."""
    diff_result = subprocess.run(
        ["git", "diff", "main...HEAD"],
        capture_output=True,
        text=True,
    )
    diff = diff_result.stdout.strip()

    prompt = (
        f"Generate a GitHub pull request description.\n"
        f"Task: {task_text}\n\n"
        f"Git diff:\n{diff[:8000]}\n\n"
        f"Use this format:\n"
        f"## Summary\n"
        f"<1-3 bullet points describing what was done>\n\n"
        f"## Changes\n"
        f"<bullet list of specific file changes>\n\n"
        f"Return ONLY the markdown description."
    )
    cmd = [
        "claude",
        "-p",
        prompt,
        "--model",
        "claude-haiku-4-5-20251001",
        "--permission-mode",
        "acceptEdits",
        "--output-format",
        "text",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    desc = result.stdout.strip()
    if not desc or result.returncode != 0:
        return f"## Summary\n- {task_text}"
    return desc


def get_task_list() -> List[str]:
    return ["add a comment Hi in the first line of @gunicorn_config.py"]
    return [
        "the task `onsen.apps.core.tasks.google_ads.invite_google_ads_account_to_managed_account` need be creted to run in schedule, but the first execution need be in the time that the task is creted",
        """
            we need create a playwright test in @playwright/tests/google_ads.spec.ts
the test dependes of `google-cleanup` project, run it first
after that, we need a test where:
1 - the user will login.
2 - add a google ads account number
3 - wait 10 seconds, we need wait the tasks be executed
4 - check in (link do google ads) if the tinuvi account is the manager of the user accont
            """,
        """
            we need create a playwright test in @playwright/tests/google_ga.spec.ts
the test dependes of `google-cleanup` project, run it first
1 - the user will login.
2 - go to google ads menu (confirmar).
3 - select the options in selects, if you have 2 options, select test-ga
4 - wait 10 seconds, we need wait the tasks be executed (confirmar se tem task)
5 - verificar em gtm as variáveis, trigers, etc
6 - verificar no ga se tem o stream
            """,
        """
            create a python code that get all itens in one slack list.
- just get ite that have a thread link and the collum completed is false
- return a list of strings with the description is the task text
""",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Orchestrate Claude agent tasks")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print raw stream-json lines instead of formatted output",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum number of fix attempts after integration test failures (default: 3)",
    )
    args = parser.parse_args()

    max_fix_attempts = args.max_attempts

    for task in get_tasks_in_slack():
        task_text = task["text"]
        task_id = task["id"]
        channel_id = task.get("channel_id")
        thread_ts = task.get("thread_ts")

        branch_name = generate_branch_name(task_text)
        if not create_branch(branch_name):
            print(c("red", "[frank] Cannot proceed without a clean branch. Exiting."))
            sys.exit(1)

        result = execute_claude(task_text, verbose=args.verbose)

        if not result["success"]:
            subprocess.run(["git", "checkout", "main"], capture_output=True, text=True)
            continue

        task_complete = False

        for attempt in range(1, max_fix_attempts + 1):
            exit_code, test_output = run_integration_tests(verbose=args.verbose)

            if exit_code != 0:
                print(
                    c(
                        "red",
                        f"[frank] Integration tests failed (attempt {attempt}/{max_fix_attempts}). Sending output to Claude...",
                    )
                )
                fix_task = test_output + "\n\nThe tasks failed, fix this even if it is not about your tasks"
                result = execute_claude(
                    fix_task,
                    session_id=result["session_id"],
                    verbose=args.verbose,
                )
                continue

            print(c("green", "[frank] Integration tests passed."))

            # Lint check: run twice, if second run fails send back to Claude
            lint_exit_code, lint_output = run_lint_formatter(verbose=args.verbose)

            if lint_exit_code == 0:
                print(c("green", "[frank] Lint-formatter passed. Task complete."))
                task_complete = True
                break

            print(
                c(
                    "red",
                    f"[frank] Lint-formatter failed (attempt {attempt}/{max_fix_attempts}). Sending output to Claude...",
                )
            )
            fix_task = lint_output + "\n\nwe need fix this lint problems"
            result = execute_claude(
                fix_task,
                session_id=result["session_id"],
                verbose=args.verbose,
            )
        else:
            print(c("red", f"[frank] Still failing after {max_fix_attempts} attempts. Moving on."))

        if task_complete:
            description = generate_task_description(task_text)

            pr_url = None
            if commit_and_push(branch_name, task_text):
                pr_url = create_pull_request(task_text)

            print(c("cyan", "[frank] Marking Slack item as done..."))
            mark_slack_item_done(task_id)
            print(c("green", "[frank] Slack item marked as done."))
            if channel_id and thread_ts:
                if pr_url:
                    description += f"\n\nPR: {pr_url}"
                print(c("cyan", "[frank] Replying to Slack thread..."))
                reply_to_slack_thread(channel_id, thread_ts, text=description)
                print(c("green", "[frank] Slack thread replied."))

            print(c("cyan", "[frank] Switching back to main branch..."))
            subprocess.run(["git", "checkout", "main"], capture_output=True, text=True)
            print(c("green", f"[frank] Task complete: {task_text[:60]}"))
        else:
            subprocess.run(["git", "checkout", "main"], capture_output=True, text=True)


def main_prompt() -> str:
    return """return JUST a json with this format:
{
    "success": true or false,
    "message: "what you did"
}

DO NOT ADD ANY WORD BEFORE OR AFTER THE JSON RESULT
DO NOT EXPLAIN NOTHING
DO NOT ADD ```json OR ``` IN RESULT

We need tha you result can be load as a json in python: json.loads(employee_string)
    """


def run_integration_tests(verbose: bool = False) -> tuple[int, str]:
    """Run integration tests and return (exit_code, output)."""
    print(c("cyan", "[frank] Running integration tests..."))

    cmd = [
        "docker",
        "compose",
        "up",
        "--remove-orphans",
        "--abort-on-container-exit",
        "--exit-code-from",
        "integration-tests",
        "integration-tests",
    ]

    if verbose:
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stdout + result.stderr
        print(output)
        return result.returncode, output

    tail_lines: deque[str] = deque(maxlen=4)
    all_output: list[str] = []
    displayed_count = 0
    is_tty = sys.stdout.isatty()
    term_width = os.get_terminal_size().columns if is_tty else 80

    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
        for line in proc.stdout:
            all_output.append(line)
            stripped = line.rstrip("\n")
            tail_lines.append(stripped)

            if is_tty:
                # Move cursor up to overwrite previous tail block
                if displayed_count > 0:
                    sys.stdout.write(f"\033[{displayed_count}A")
                # Clear from cursor to end of screen
                sys.stdout.write("\033[J")

                # Print current tail lines in gray, truncated to terminal width
                for tl in tail_lines:
                    truncated = tl[: term_width - 1]
                    sys.stdout.write(f"\033[2m{truncated}\033[0m\n")
                sys.stdout.flush()
                displayed_count = len(tail_lines)

    # Clear the tail lines after process finishes
    if is_tty and displayed_count > 0:
        sys.stdout.write(f"\033[{displayed_count}A\033[J")
        sys.stdout.flush()

    return proc.returncode, "".join(all_output)


def run_lint_formatter(verbose: bool = False) -> tuple[int, str]:
    """Run lint-formatter twice. Return the exit code and output of the second run.

    The first run applies auto-fixes. The second run verifies everything is clean.
    If the second run exits non-zero, there are lint problems that need manual fixing.
    """
    cmd = ["docker", "compose", "up", "lint-formatter"]

    for run_number in (1, 2):
        print(c("cyan", f"[frank] Running lint-formatter (pass {run_number}/2)..."))

        if verbose:
            result = subprocess.run(cmd, capture_output=True, text=True)
            output = result.stdout + result.stderr
            print(output)
            if run_number == 1:
                continue
            return result.returncode, output

        tail_lines: deque[str] = deque(maxlen=4)
        all_output: list[str] = []
        displayed_count = 0
        is_tty = sys.stdout.isatty()
        term_width = os.get_terminal_size().columns if is_tty else 80

        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
            for line in proc.stdout:
                all_output.append(line)
                stripped = line.rstrip("\n")
                tail_lines.append(stripped)

                if is_tty:
                    if displayed_count > 0:
                        sys.stdout.write(f"\033[{displayed_count}A")
                    sys.stdout.write("\033[J")

                    for tl in tail_lines:
                        truncated = tl[: term_width - 1]
                        sys.stdout.write(f"\033[2m{truncated}\033[0m\n")
                    sys.stdout.flush()
                    displayed_count = len(tail_lines)

        if is_tty and displayed_count > 0:
            sys.stdout.write(f"\033[{displayed_count}A\033[J")
            sys.stdout.flush()

        if run_number == 1:
            continue
        return proc.returncode, "".join(all_output)

    # Should never reach here, but satisfy a type checker
    return 1, ""


def execute_claude(task: str, session_id: str | None = None, verbose: bool = False) -> dict:

    prompt = main_prompt()
    user_prompt = task + "\n" + prompt

    initial_cmd = [
        "claude",
        "-p",
        user_prompt,
        "--output-format",
        "stream-json",
        "--permission-mode",
        "acceptEdits",
        "--verbose",
    ]

    args = []
    if session_id:
        # `-r` = resume the session id... if use `--session_id` the claude cli break
        # Error: Session ID 13964e72-db8a-431e-a8da-f2c23a7bd4d5 is already in use.
        args.extend(["-r", session_id])

    cmd = initial_cmd + args

    result = {"success": False, "session_id": None}

    with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True) as p:
        for line in p.stdout:
            if verbose:
                print(line, end="")
            else:
                formatted = format_stream_line(line)
                if formatted is not None:
                    print(formatted)

            stripped = line.strip()
            if stripped:
                try:
                    data = json.loads(stripped)
                    if not isinstance(data, dict):
                        continue
                    if data.get("type") == "system" and data.get("subtype") == "init":
                        result["session_id"] = data.get("session_id")
                    elif data.get("type") == "result":
                        result["success"] = not data.get("is_error", False)
                        if data.get("session_id"):
                            result["session_id"] = data.get("session_id")
                except json.JSONDecodeError:
                    pass

    return result


if __name__ == "__main__":
    import time
    import traceback

    POLL_INTERVAL = 30

    print(c("cyan", f"[frank] Starting polling loop (every {POLL_INTERVAL}s). Press Ctrl+C to stop."))
    while True:
        try:
            main()
        except KeyboardInterrupt:
            raise
        except Exception:
            print(c("red", "[frank] Fatal error in main loop:"))
            traceback.print_exc()
            sys.exit(1)

        try:
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            print(c("cyan", "\n[frank] Stopped."))
            break
