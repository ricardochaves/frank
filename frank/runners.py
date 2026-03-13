import os
import subprocess
import sys
from collections import deque

from frank.colors import c


def run_integration_tests(verbose: bool = False, cwd: str | None = None) -> tuple[int, str]:
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
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
        output = result.stdout + result.stderr
        print(output)
        return result.returncode, output

    return _run_with_tail(cmd, cwd=cwd)


def run_lint_formatter(verbose: bool = False, cwd: str | None = None) -> tuple[int, str]:
    """Run lint-formatter twice. Return the exit code and output of the second run."""
    cmd = ["docker", "compose", "up", "lint-formatter"]

    for run_number in (1, 2):
        print(c("cyan", f"[frank] Running lint-formatter (pass {run_number}/2)..."))

        if verbose:
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
            output = result.stdout + result.stderr
            print(output)
            if run_number == 1:
                continue
            return result.returncode, output

        exit_code, output = _run_with_tail(cmd, cwd=cwd)
        if run_number == 1:
            continue
        return exit_code, output

    return 1, ""


def _run_with_tail(cmd: list[str], cwd: str | None = None) -> tuple[int, str]:
    """Run a command showing a rolling 4-line tail in the terminal."""
    tail_lines: deque[str] = deque(maxlen=4)
    all_output: list[str] = []
    displayed_count = 0
    is_tty = sys.stdout.isatty()
    term_width = os.get_terminal_size().columns if is_tty else 80

    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=cwd) as proc:
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

    return proc.returncode, "".join(all_output)
