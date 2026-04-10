"""Integration tests for the pytest-regression plugin."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo. Tests must add files and create the base branch themselves."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"git {args} failed:\n{result.stderr}"
        return result

    git("init")
    git("config", "user.email", "test@test.com")
    git("config", "user.name", "Test")

    (repo / "conftest.py").write_text("")
    git("add", ".")
    git("commit", "-m", "initial")

    return repo


def _git(repo, *args):
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True
    )
    assert result.returncode == 0, f"git {args} failed:\n{result.stderr}"


def _run_pytest(repo: Path, *args: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    import os

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )


def test_no_regression_flag_runs_normally(git_repo):
    """Without --regression, tests run as normal."""
    (git_repo / "test_simple.py").write_text("def test_add():\n    assert 1 + 1 == 2\n")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "add test")

    result = _run_pytest(git_repo, "test_simple.py")
    assert result.returncode == 0


def test_none_return_not_compared(git_repo):
    """Tests returning None skip regression comparison (no REGRESSION section)."""
    (git_repo / "test_none.py").write_text("def test_none():\n    return None\n")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "add test")
    _git(git_repo, "branch", "base")  # base branch has the same test

    result = _run_pytest(git_repo, "test_none.py", "--drift=base")
    assert result.returncode == 0
    # No regression output when nothing was compared
    assert "DRIFT" not in result.stdout


def test_matching_scalar_values_pass(git_repo):
    """When head and base both return the same value, no regression reported."""
    (git_repo / "test_scalar.py").write_text("def test_value():\n    return 42\n")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "add test")
    _git(git_repo, "branch", "base")  # base has this version too

    result = _run_pytest(git_repo, "test_scalar.py", "--drift=base")
    assert result.returncode == 0
    assert "FAILED" not in result.stdout or "0 failed" in result.stdout


def test_differing_scalar_values_fail(git_repo):
    """When head returns 42 but base returns 43, regression is detected."""
    # Commit the base version (returns 43) first
    (git_repo / "test_scalar.py").write_text("def test_value():\n    return 43\n")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "base version")
    _git(git_repo, "branch", "base")  # create base branch here

    # Now update main to return 42
    (git_repo / "test_scalar.py").write_text("def test_value():\n    return 42\n")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "head version")

    result = _run_pytest(git_repo, "test_scalar.py", "--drift=base", "-v")
    # Should detect regression: 42 (head) != 43 (base)
    assert "FAILED" in result.stdout or "mismatch" in result.stdout.lower()


def test_env_var_activates_plugin(git_repo):
    """PYTEST_DRIFT_BASE_BRANCH env var activates the plugin."""
    (git_repo / "test_env.py").write_text("def test_noop():\n    pass\n")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "add test")
    _git(git_repo, "branch", "base")

    result = _run_pytest(
        git_repo,
        "test_env.py",
        extra_env={"PYTEST_DRIFT_BASE_BRANCH": "base"},
    )
    assert result.returncode == 0


def test_async_test_return_value_compared(git_repo):
    """Async tests that return a value are compared against the base branch."""
    test_code = (
        "import pytest\n"
        "import asyncio\n"
        "@pytest.mark.asyncio\n"
        "async def test_async_value():\n"
        "    await asyncio.sleep(0)\n"
        "    return 99\n"
    )
    (git_repo / "test_async.py").write_text(test_code)
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "add async test")
    _git(git_repo, "branch", "base")  # base has same test (returns 99)

    result = _run_pytest(
        git_repo, "test_async.py", "--drift=base",
        "-p", "asyncio_mode", "--asyncio-mode=auto",
    )
    # Both sides return 99 — no regression
    assert "FAILED" not in result.stdout or "0 failed" in result.stdout


def test_invalid_branch_shows_error(git_repo):
    """A non-existent branch name reports an error in regression output."""
    (git_repo / "test_inv.py").write_text("def test_x():\n    return 1\n")
    _git(git_repo, "add", ".")
    _git(git_repo, "commit", "-m", "add test")

    result = _run_pytest(git_repo, "test_inv.py", "--drift=nonexistent_branch_xyz")
    # The plugin reports the git error; stderr or stdout should contain the message
    combined = result.stdout + result.stderr
    assert "nonexistent_branch_xyz" in combined or "invalid reference" in combined
