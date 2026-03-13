import json
import subprocess

from frank.colors import c
from frank.formatter import format_stream_line


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


def execute_claude(task: str, session_id: str | None = None, verbose: bool = False, cwd: str | None = None) -> dict:
    prompt = main_prompt()
    user_prompt = task + "\n" + prompt

    cmd = [
        "claude",
        "-p",
        user_prompt,
        "--output-format",
        "stream-json",
        "--dangerously-skip-permissions",
        "--verbose",
    ]

    if session_id:
        cmd.extend(["-r", session_id])

    result = {"success": False, "session_id": None}

    with subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True, cwd=cwd) as p:
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
