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
        # Ensure the base branch ref is available locally (CI runners
        # typically do shallow, single-branch clones).
        subprocess.run(
            ["git", "fetch", "origin", self.branch],
            cwd=self.git_root,
            capture_output=True,
        )

        # Prefer the freshly fetched remote ref to avoid stale local-branch
        # state, but fall back to the local branch when there's no matching
        # remote (e.g. local-only repos).
        ref = f"origin/{self.branch}"
        if subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", ref],
            cwd=self.git_root,
            capture_output=True,
        ).returncode != 0:
            ref = self.branch

        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(self.worktree_path), ref],
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


def _build_base_env(worktree_path: Path, results_dir: Path, extra_env: dict[str, str] | None) -> dict[str, str]:
    import os

    env = os.environ.copy()
    env["PYTEST_DRIFT_MODE"] = "base"
    env["PYTEST_DRIFT_RESULTS_DIR"] = str(results_dir)
    # Prevent the subprocess from re-activating regression mode via CLI option
    env.pop("PYTEST_DRIFT_BASE_BRANCH", None)
    # Ensure the worktree root is on sys.path so imports resolve even if the
    # base branch lacks a setup.cfg / pyproject.toml with pythonpath config.
    existing = env.get("PYTHONPATH", "")
    wt = str(worktree_path)
    env["PYTHONPATH"] = f"{wt}{os.pathsep}{existing}" if existing else wt
    if extra_env:
        env.update(extra_env)
    return env


def collect_base_node_ids(worktree_path: Path, node_ids: list[str], env: dict[str, str]) -> set[str]:
    """Return the node ids that actually collect in the base worktree.

    Passing an explicit node id that no longer exists on the base branch (e.g. a
    test re-parametrized on HEAD, so its ``[param]`` suffix changed) makes pytest
    raise a "not found" UsageError that aborts the *entire* run — and
    ``--continue-on-collection-errors`` does not rescue it. So we first collect
    the base branch's real node ids (per file, tolerating import errors) and let
    the caller pass only the intersection.
    """
    files = sorted({nid.split("::")[0] for nid in node_ids if "::" in nid})
    if not files:
        return set()

    import json
    import os
    import tempfile

    # Read node ids straight off the collected items via an in-process plugin
    # rather than parsing stdout: the target repo's addopts (e.g. ``-v``) change
    # --collect-only formatting, which would otherwise defeat text parsing.
    out_fd, out_name = tempfile.mkstemp(suffix=".json")
    os.close(out_fd)
    script_fd, script_name = tempfile.mkstemp(suffix=".py")
    os.close(script_fd)

    args = [
        "--collect-only", "--continue-on-collection-errors",
        "--rootdir", str(worktree_path),
        *files,
    ]
    script_src = (
        "import sys, json, pytest\n"
        "class _C:\n"
        "    def pytest_collection_modifyitems(self, items):\n"
        f"        json.dump([i.nodeid for i in items], open({json.dumps(out_name)}, 'w'))\n"
        f"sys.exit(pytest.main({json.dumps(args)}, plugins=[_C()]))\n"
    )
    with open(script_name, "w") as f:
        f.write(script_src)

    try:
        subprocess.run(
            [sys.executable, script_name],
            cwd=worktree_path,
            env=env,
            capture_output=True,
            text=True,
        )
        try:
            with open(out_name) as f:
                ids = json.load(f)
        except (OSError, ValueError):
            ids = []
    finally:
        for p in (out_name, script_name):
            try:
                os.unlink(p)
            except OSError:
                pass

    return {nid.replace("\\", "/") for nid in ids}


def run_base_branch(
    worktree_path: Path,
    node_ids: list[str],
    results_dir: Path,
    extra_env: dict[str, str] | None = None,
) -> "subprocess.Popen[bytes]| None":
    """
    Launch a pytest subprocess in the worktree for the base branch.

    The subprocess runs in BASE mode: it captures return values and writes
    them to results_dir/base/, but does not start another subprocess.

    Returns None if no requested node ids collect on the base branch.
    """
    env = _build_base_env(worktree_path, results_dir, extra_env)

    # Only run node ids that actually exist on the base branch; a single stale
    # id would otherwise abort the whole base run and void every comparison.
    available = collect_base_node_ids(worktree_path, node_ids, env)
    runnable = [nid for nid in node_ids if nid.replace("\\", "/") in available]
    if not runnable:
        return None

    # Write a wrapper script instead of passing node_ids on the command line,
    # to avoid Windows' command-line length limit ([WinError 206]).
    import json
    import tempfile
    args = [
        "--no-header", "-q", "--tb=no",
        "--continue-on-collection-errors",
        "-p", "pytest_drift",
        "--rootdir", str(worktree_path),
        *runnable,
    ]
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
