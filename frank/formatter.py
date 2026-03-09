import json

from frank.colors import c

# Maps tool_use_id -> agent description for subagent name tracking
_agent_names: dict[str, str] = {}


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
            c("cyan", "[session] ") + f"model={c('bold', model)}",
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
        tool_use_id = data.get("tool_use_id", "")
        if tool_use_id and desc:
            _agent_names.setdefault(tool_use_id, desc)
        parts = [c("magenta", "[sub-agent] ") + c("bold", desc)]
        if task_type:
            parts[0] += f"  {c('dim', task_type)}"
        return parts[0]
    return None


def _format_assistant(data: dict) -> str | None:
    message = data.get("message", {})
    content_blocks = message.get("content", [])
    parent_id = data.get("parent_tool_use_id")
    is_subagent = parent_id is not None
    indent = "  " if is_subagent else ""
    agent_label = ""
    if is_subagent and parent_id in _agent_names:
        agent_label = c("dim", f"({_agent_names[parent_id]}) ")
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
                prefix = c("magenta", "[sub-agent] ") + agent_label if is_subagent else c("green", "[output] ")
                parts.append(indent + prefix + text)

        elif block_type == "tool_use":
            tool_name = block.get("name", "?")
            tool_input = block.get("input", {})
            # Track agent names from Agent tool calls
            if tool_name == "Agent" and not is_subagent:
                tool_id = block.get("id", "")
                desc = tool_input.get("description", "")
                if tool_id and desc:
                    _agent_names[tool_id] = desc
            summary = _summarize_tool_input(tool_name, tool_input)
            prefix = indent + ((c("magenta", "[sub-tool] ") + agent_label) if is_subagent else c("yellow", "[tool] "))
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
        return c("magenta", "[sub-agent done] ") + c("dim", f"status={status}") + (f" {c('dim', preview)}" if preview else "")

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
