"""Git worktree management and base-branch subprocess orchestration."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import IO


class WorktreeError(Exception):
    pass


def filter_existing_node_ids(worktree_path: Path, node_ids: list[str]) -> list[str]:
    """Filter node_ids to only those whose test functions exist in the worktree."""
    existing = []
    for node_id in node_ids:
        # node_id format: "tests/file.py::test_name" or "tests/file.py::test_name[param]"
        parts = node_id.split("::")
        if len(parts) < 2:
            existing.append(node_id)
            continue

        file_path = worktree_path / parts[0]
        if not file_path.exists():
            continue

        # Extract function name (strip parametrize suffix)
        func_name = parts[1].split("[")[0]

        try:
            content = file_path.read_text()
            if f"def {func_name}" in content:
                existing.append(node_id)
        except Exception:
            existing.append(node_id)

    return existing


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
    extra_env: dict[str, str] | None = None,
) -> "subprocess.Popen[bytes]":
    """
    Launch a pytest subprocess in the worktree for the base branch.

    The subprocess runs in BASE mode: it captures return values and writes
    them to results_dir/base/, but does not start another subprocess.
    """
    import os

    env = os.environ.copy()
    env["PYTEST_DRIFT_MODE"] = "base"
    env["PYTEST_DRIFT_RESULTS_DIR"] = str(results_dir)
    # Prevent the subprocess from re-activating regression mode via CLI option
    env.pop("PYTEST_DRIFT_BASE_BRANCH", None)
    if extra_env:
        env.update(extra_env)

    # Write a wrapper script instead of passing node_ids on the command line,
    # to avoid Windows' command-line length limit ([WinError 206]).
    import json
    import tempfile
    args = ["--no-header", "-q", "--tb=no", "-p", "pytest_drift", *node_ids]
    script = tempfile.NamedTemporaryFile(
        suffix=".py", delete=False, mode="w", dir=str(results_dir),
    )
    script.write(f"import sys, pytest; sys.exit(pytest.main({json.dumps(args)}))")
    script.close()

    cmd = [sys.executable, script.name]

    proc = subprocess.Popen(
        cmd,
        cwd=worktree_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc
