import os
import subprocess
from pathlib import Path

from frank.colors import c

DEFAULT_WORKSPACE_DIR = os.path.expanduser("~/.frank/repos")
REPOS_FILE = "repos.txt"


def load_repos(path: str = REPOS_FILE) -> list[str]:
    """Read repos.txt and return list of repo identifiers (owner/repo or full URL)."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"repos.txt not found at {path}")

    repos = []
    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                repos.append(stripped)

    if not repos:
        raise ValueError("repos.txt is empty — add at least one repository")

    return repos


def resolve_repo(task_text: str, repos: list[str]) -> str | None:
    """Use Claude Haiku to pick the right repo for a task. Returns repo identifier or None."""
    if len(repos) == 1:
        print(c("cyan", f"[frank] Single repo available: {repos[0]}"))
        return repos[0]

    print(c("cyan", "[frank] Resolving repository for task..."))

    repo_list = "\n".join(f"- {r}" for r in repos)
    prompt = (
        f"You must decide which repository a task should be executed in.\n\n"
        f"Task:\n{task_text}\n\n"
        f"Available repositories:\n{repo_list}\n\n"
        f"Rules:\n"
        f"- Reply with ONLY the repository identifier exactly as listed above\n"
        f"- If the task clearly does not match any repository, reply with NONE\n"
        f"- No quotes, no explanation, no extra text"
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
    answer = result.stdout.strip().strip('"').strip("'")

    if not answer or result.returncode != 0 or answer.upper() == "NONE":
        print(c("yellow", f"[frank] Could not resolve repo (answer={answer!r})"))
        return None

    if answer in repos:
        print(c("green", f"[frank] Resolved repo: {answer}"))
        return answer

    # Fuzzy match: check if answer is a substring of any repo
    for repo in repos:
        if answer.lower() in repo.lower() or repo.lower() in answer.lower():
            print(c("green", f"[frank] Resolved repo: {repo}"))
            return repo

    print(c("yellow", f"[frank] Haiku returned unknown repo: {answer!r}"))
    return None


def _repo_to_clone_url(repo: str) -> str:
    """Convert owner/repo shorthand to a full git clone URL."""
    if repo.startswith("http://") or repo.startswith("https://") or repo.startswith("git@"):
        return repo
    return f"git@github.com:{repo}.git"


def _repo_to_local_path(repo: str, workspace_dir: str) -> str:
    """Convert a repo identifier to a local directory path."""
    # Strip URL parts to get owner/repo
    name = repo
    for prefix in ("git@github.com:", "https://github.com/", "http://github.com/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    name = name.removesuffix(".git").strip("/")

    return os.path.join(workspace_dir, name)


def ensure_clone(repo: str, workspace_dir: str | None = None) -> str:
    """Clone or update a repo. Returns absolute path to the local clone."""
    workspace = workspace_dir or os.environ.get("FRANK_WORKSPACE_DIR", DEFAULT_WORKSPACE_DIR)
    local_path = _repo_to_local_path(repo, workspace)
    clone_url = _repo_to_clone_url(repo)

    if os.path.isdir(os.path.join(local_path, ".git")):
        print(c("cyan", f"[frank] Updating existing clone: {local_path}"))
        subprocess.run(["git", "fetch", "origin"], capture_output=True, text=True, cwd=local_path)
        subprocess.run(["git", "checkout", "main"], capture_output=True, text=True, cwd=local_path)
        subprocess.run(["git", "pull", "--ff-only"], capture_output=True, text=True, cwd=local_path)
    else:
        print(c("cyan", f"[frank] Cloning {clone_url} into {local_path}..."))
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", clone_url, local_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(c("red", f"[frank] Clone failed: {result.stderr.strip()}"))
            raise RuntimeError(f"Failed to clone {clone_url}: {result.stderr.strip()}")

    print(c("green", f"[frank] Repo ready: {local_path}"))
    return os.path.abspath(local_path)
