import argparse
import subprocess
import sys

from frank.claude import execute_claude
from frank.colors import c
from frank.git import (
    commit_and_push,
    create_branch,
    create_pull_request,
    generate_branch_name,
    generate_task_description,
)
from frank.repo import ensure_clone, load_repos, resolve_repo
from frank.runners import run_integration_tests, run_lint_formatter
from frank.tasks import get_task_source


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
    parser.add_argument(
        "--source",
        choices=["slack", "monday", "file"],
        default="slack",
        help="Task source to use (default: slack)",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Base branch to work from and target PRs against (default: main)",
    )
    args = parser.parse_args()

    max_fix_attempts = args.max_attempts
    base_branch = args.branch
    source = get_task_source(args.source)

    repos = load_repos()

    for task in source.get_tasks():
        # Resolve which repo this task belongs to
        repo = resolve_repo(task.text, repos)
        if repo is None:
            print(c("yellow", f"[frank] Could not determine repo for task: {task.text[:60]}"))
            source.reply(task, "Não consegui identificar o repositório para essa tarefa.")
            continue

        # Clone or update the repo
        try:
            repo_path = ensure_clone(repo, base_branch=base_branch)
        except RuntimeError as e:
            print(c("red", f"[frank] {e}"))
            source.reply(task, f"Erro ao clonar repositório: {repo}")
            continue

        branch_name = generate_branch_name(task.text)
        if not create_branch(branch_name, base_branch=base_branch, cwd=repo_path):
            print(c("red", "[frank] Cannot proceed without a clean branch. Skipping task."))
            continue

        result = execute_claude(task.text, verbose=args.verbose, cwd=repo_path)

        if not result["success"]:
            subprocess.run(["git", "checkout", base_branch], capture_output=True, text=True, cwd=repo_path)
            continue

        task_complete = False

        for attempt in range(1, max_fix_attempts + 1):
            exit_code, test_output = run_integration_tests(verbose=args.verbose, cwd=repo_path)

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
                    cwd=repo_path,
                )
                continue

            print(c("green", "[frank] Integration tests passed."))

            lint_exit_code, lint_output = run_lint_formatter(verbose=args.verbose, cwd=repo_path)

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
                cwd=repo_path,
            )
        else:
            print(c("red", f"[frank] Still failing after {max_fix_attempts} attempts. Moving on."))

        if task_complete:
            description = generate_task_description(task.text, cwd=repo_path)

            pr_url = None
            if commit_and_push(branch_name, task.text, cwd=repo_path):
                pr_url = create_pull_request(task.text, base_branch=base_branch, cwd=repo_path)

            print(c("cyan", "[frank] Marking task as done..."))
            source.mark_done(task)
            print(c("green", "[frank] Task marked as done."))

            if pr_url:
                description += f"\n\nPR: {pr_url}"
            print(c("cyan", "[frank] Posting reply..."))
            source.reply(task, description)
            print(c("green", "[frank] Reply posted."))

            print(c("cyan", f"[frank] Switching back to {base_branch} branch..."))
            subprocess.run(["git", "checkout", base_branch], capture_output=True, text=True, cwd=repo_path)
            print(c("green", f"[frank] Task complete: {task.text[:60]}"))
        else:
            subprocess.run(["git", "checkout", base_branch], capture_output=True, text=True, cwd=repo_path)
