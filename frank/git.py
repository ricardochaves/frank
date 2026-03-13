import re
import subprocess

from frank.colors import c


def generate_task_description(task_text: str, cwd: str | None = None) -> str:
    """Get the git diff and call Claude Haiku to generate a task description."""
    print(c("cyan", "[frank] Generating task description..."))

    diff_result = subprocess.run(
        ["git", "diff", "HEAD"],
        capture_output=True,
        text=True,
        cwd=cwd,
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
        "--dangerously-skip-permissions",
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
        "--dangerously-skip-permissions",
        "--output-format",
        "text",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    branch = result.stdout.strip().strip("`").strip('"').strip("'")

    if not branch or result.returncode != 0 or not branch.startswith("frank/"):
        sanitized = re.sub(r"[^a-z0-9]+", "-", task_text.lower()[:40]).strip("-")
        return f"frank/{sanitized}"
    return branch


def create_branch(branch_name: str, cwd: str | None = None) -> bool:
    """Create and checkout a git branch from main, or switch to it if it already exists."""
    subprocess.run(["git", "checkout", "main"], capture_output=True, text=True, cwd=cwd)
    subprocess.run(["git", "pull", "--ff-only"], capture_output=True, text=True, cwd=cwd)

    result = subprocess.run(
        ["git", "checkout", "-b", branch_name],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        result = subprocess.run(
            ["git", "checkout", branch_name],
            capture_output=True,
            text=True,
            cwd=cwd,
        )
        if result.returncode != 0:
            print(c("red", f"[frank] Failed to create/switch branch: {result.stderr.strip()}"))
            return False
        print(c("green", f"[frank] Switched to existing branch: {branch_name}"))
        return True
    print(c("green", f"[frank] Created branch: {branch_name}"))
    return True


def generate_commit_message(task_text: str, cwd: str | None = None) -> str:
    """Use Claude Haiku to generate a conventional commit message from staged changes."""
    print(c("cyan", "[frank] Generating commit message..."))
    diff_result = subprocess.run(
        ["git", "diff", "--staged"],
        capture_output=True,
        text=True,
        cwd=cwd,
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
        "--dangerously-skip-permissions",
        "--output-format",
        "text",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    msg = result.stdout.strip()
    if not msg or result.returncode != 0:
        return f"feat: {task_text[:60]}"
    return msg


def commit_and_push(branch_name: str, task_text: str, cwd: str | None = None) -> bool:
    """Stage all changes, generate commit message, commit, and push."""
    print(c("cyan", "[frank] Committing and pushing changes..."))

    subprocess.run(["git", "add", "."], capture_output=True, text=True, cwd=cwd)

    status = subprocess.run(
        ["git", "diff", "--staged", "--quiet"],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if status.returncode == 0:
        print(c("yellow", "[frank] No changes to commit."))
        return False

    commit_msg = generate_commit_message(task_text, cwd=cwd)
    result = subprocess.run(
        ["git", "commit", "-m", commit_msg],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        print(c("red", f"[frank] Failed to commit: {result.stderr.strip()}"))
        return False
    print(c("green", f"[frank] Committed: {commit_msg.split(chr(10))[0]}"))

    result = subprocess.run(
        ["git", "push", "-u", "origin", branch_name],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        print(c("red", f"[frank] Failed to push: {result.stderr.strip()}"))
        return False
    print(c("green", f"[frank] Pushed to origin/{branch_name}"))
    return True


def create_pull_request(task_text: str, cwd: str | None = None) -> str | None:
    """Create a GitHub PR using gh CLI. Returns the PR URL or None."""
    print(c("cyan", "[frank] Creating pull request..."))

    pr_title = _generate_pr_title(task_text)
    pr_body = _generate_pr_description(task_text, cwd=cwd)

    result = subprocess.run(
        ["gh", "pr", "create", "--title", pr_title, "--body", pr_body],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        print(c("red", f"[frank] Failed to create PR: {result.stderr.strip()}"))
        return None

    pr_url = result.stdout.strip()
    print(c("green", f"[frank] Created PR: {pr_url}"))
    return pr_url


def _generate_pr_title(task_text: str) -> str:
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
        "--dangerously-skip-permissions",
        "--output-format",
        "text",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    title = result.stdout.strip().strip('"').strip("'")
    if not title or result.returncode != 0:
        return task_text[:70]
    return title[:70]


def _generate_pr_description(task_text: str, cwd: str | None = None) -> str:
    diff_result = subprocess.run(
        ["git", "diff", "main...HEAD"],
        capture_output=True,
        text=True,
        cwd=cwd,
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
        "--dangerously-skip-permissions",
        "--output-format",
        "text",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    desc = result.stdout.strip()
    if not desc or result.returncode != 0:
        return f"## Summary\n- {task_text}"
    return desc
