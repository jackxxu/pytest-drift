"""Git worktree management and base-branch subprocess orchestration."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import IO


class WorktreeError(Exception):
    pass


def get_git_root(cwd: Path) -> Path:
    """Return the root of the git repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise WorktreeError(
            f"Failed to find git root from {cwd}: {result.stderr.strip()}"
        )
    return Path(result.stdout.strip())


class WorktreeManager:
    """Context manager that creates and removes a git worktree."""

    def __init__(self, git_root: Path, worktree_path: Path, branch: str) -> None:
        self.git_root = git_root
        self.worktree_path = worktree_path
        self.branch = branch

    def __enter__(self) -> Path:
        result = subprocess.run(
            ["git", "worktree", "add", str(self.worktree_path), self.branch],
            cwd=self.git_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise WorktreeError(
                f"git worktree add failed for branch '{self.branch}':\n"
                f"{result.stderr.strip()}"
            )
        return self.worktree_path

    def __exit__(self, *args) -> None:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(self.worktree_path)],
            cwd=self.git_root,
            capture_output=True,
        )


def run_base_branch(
    worktree_path: Path,
    node_ids: list[str],
    results_dir: Path,
    base_python: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> "subprocess.Popen[bytes]":
    """
    Launch a pytest subprocess in the worktree for the base branch.

    The subprocess runs in BASE mode: it captures return values and writes
    them to results_dir/base/, but does not start another subprocess.

    base_python: path to an alternative Python executable (e.g. a venv's
    python) to use for the base branch run. Defaults to the current
    interpreter (sys.executable).
    """
    import os

    python = base_python or sys.executable

    env = os.environ.copy()
    env["PYTEST_DRIFT_MODE"] = "base"
    env["PYTEST_DRIFT_RESULTS_DIR"] = str(results_dir)
    # Prevent the subprocess from re-activating regression mode via CLI option
    env.pop("PYTEST_DRIFT_BASE_BRANCH", None)
    if extra_env:
        env.update(extra_env)

    cmd = [
        python,
        "-m",
        "pytest",
        "--no-header",
        "-q",
        "--tb=no",
        "-p",
        "pytest_drift",
        *node_ids,
    ]

    proc = subprocess.Popen(
        cmd,
        cwd=worktree_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc
