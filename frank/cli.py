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
        choices=["slack", "monday"],
        default="slack",
        help="Task source to use (default: slack)",
    )
    args = parser.parse_args()

    max_fix_attempts = args.max_attempts
    source = get_task_source(args.source)

    for task in source.get_tasks():
        branch_name = generate_branch_name(task.text)
        if not create_branch(branch_name):
            print(c("red", "[frank] Cannot proceed without a clean branch. Exiting."))
            sys.exit(1)

        result = execute_claude(task.text, verbose=args.verbose)

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
            description = generate_task_description(task.text)

            pr_url = None
            if commit_and_push(branch_name, task.text):
                pr_url = create_pull_request(task.text)

            print(c("cyan", "[frank] Marking task as done..."))
            source.mark_done(task)
            print(c("green", "[frank] Task marked as done."))

            if pr_url:
                description += f"\n\nPR: {pr_url}"
            print(c("cyan", "[frank] Posting reply..."))
            source.reply(task, description)
            print(c("green", "[frank] Reply posted."))

            print(c("cyan", "[frank] Switching back to main branch..."))
            subprocess.run(["git", "checkout", "main"], capture_output=True, text=True)
            print(c("green", f"[frank] Task complete: {task.text[:60]}"))
        else:
            subprocess.run(["git", "checkout", "main"], capture_output=True, text=True)
