"""Core pytest plugin: hooks, orchestration."""
from __future__ import annotations

import asyncio
import functools
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from . import ci as ci_module
from . import compare as cmp_module
from . import storage
from .pandas_utils import ComparisonResult
from .report import format_regression_summary
from .runner import WorktreeError, WorktreeManager, get_git_root, run_base_branch

if TYPE_CHECKING:
    pass

_RESULTS_DIR_ENV = "PYTEST_DRIFT_RESULTS_DIR"
_MODE_ENV = "PYTEST_DRIFT_MODE"


class RegressionPlugin:
    def __init__(
        self,
        base_branch: str,
        results_dir: Path,
        mode: str,  # "head" or "base"
    ) -> None:
        self.base_branch = base_branch
        self.results_dir = results_dir
        self.mode = mode

        # Populated during the HEAD run
        self._head_node_ids: list[str] = []
        self._collected_node_ids: list[str] = []

        # Background thread that runs the base subprocess
        self._base_thread: threading.Thread | None = None
        self._base_proc = None
        self._worktree_mgr: WorktreeManager | None = None
        self._worktree_path: Path | None = None
        self._git_root: Path | None = None

        # Return values captured by the wrapping in pytest_itemcollected
        self._captured_results: dict = {}

        # Final comparison results (populated in sessionfinish)
        self._comparison_results: list[ComparisonResult] = []
        self._missing_base: list[str] = []
        self._base_stderr: str = ""

    # ------------------------------------------------------------------
    # Hook: after collection, start base-branch run in background (HEAD only)
    # ------------------------------------------------------------------
    def pytest_collection_finish(self, session: pytest.Session) -> None:
        if self.mode != "head":
            return

        self._collected_node_ids = [item.nodeid for item in session.items]

        if not self._collected_node_ids:
            return

        try:
            self._git_root = get_git_root(Path(session.config.rootdir))
        except WorktreeError as e:
            pytest.exit(f"pytest-regression: {e}", returncode=3)

        worktree_path = Path(tempfile.mkdtemp(prefix="pytest_regression_wt_"))
        self._worktree_path = worktree_path
        self._worktree_mgr = WorktreeManager(
            self._git_root, worktree_path, self.base_branch
        )

        def _run_base() -> None:
            try:
                self._worktree_mgr.__enter__()
            except WorktreeError as e:
                # Store error; will be reported in sessionfinish
                self._base_stderr = str(e)
                return

            try:
                proc = run_base_branch(
                    worktree_path,
                    self._collected_node_ids,
                    self.results_dir,
                )
                self._base_proc = proc
                stdout, stderr = proc.communicate()
                self._base_stderr = stderr.decode(errors="replace")
            finally:
                self._worktree_mgr.__exit__(None, None, None)
                # Clean up the temp worktree dir
                try:
                    shutil.rmtree(worktree_path, ignore_errors=True)
                except Exception:
                    pass

        self._base_thread = threading.Thread(target=_run_base, daemon=True)
        self._base_thread.start()

    # ------------------------------------------------------------------
    # Hook: wrap test functions at collection time so the capturing
    # wrapper is in place *before* pytest-asyncio's runtest() wraps
    # the obj with _synchronize_coroutine.
    # ------------------------------------------------------------------
    def pytest_itemcollected(self, item: pytest.Item) -> None:
        if not isinstance(item, pytest.Function):
            return

        original_obj = item.obj
        is_async = asyncio.iscoroutinefunction(original_obj)
        captured_results = self._captured_results

        if is_async:
            @functools.wraps(original_obj)
            async def capturing_wrapper(*args, **kwargs):
                result = await original_obj(*args, **kwargs)
                if result is not None:
                    captured_results[item.nodeid] = result
                return result

            item.obj = capturing_wrapper
        else:
            @functools.wraps(original_obj)
            def capturing_wrapper(*args, **kwargs):
                result = original_obj(*args, **kwargs)
                if result is not None:
                    captured_results[item.nodeid] = result
                return result

            item.obj = capturing_wrapper

    # ------------------------------------------------------------------
    # Hook: store captured return values after each test runs
    # ------------------------------------------------------------------
    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_pyfunc_call(self, pyfuncitem: pytest.Function):
        outcome = yield

        return_value = self._captured_results.pop(pyfuncitem.nodeid, None)

        if return_value is not None:
            result_path = storage.make_result_path(
                self.results_dir, self.mode, pyfuncitem.nodeid
            )
            try:
                storage.serialize(return_value, result_path)
                if self.mode == "head":
                    self._head_node_ids.append(pyfuncitem.nodeid)
            except Exception as e:
                import warnings

                warnings.warn(
                    f"pytest-regression: could not serialize return value for "
                    f"{pyfuncitem.nodeid!r}: {e}",
                    stacklevel=2,
                )

        return outcome

    # ------------------------------------------------------------------
    # Hook: wait for base, compare, clean up
    # ------------------------------------------------------------------
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if self.mode != "head":
            return

        # Wait for the base subprocess
        if self._base_thread is not None:
            self._base_thread.join()

        if not self._head_node_ids:
            return

        # Compare head vs base for each test that returned a value
        for node_id in self._head_node_ids:
            head_path = storage.make_result_path(self.results_dir, "head", node_id)
            base_path = storage.make_result_path(self.results_dir, "base", node_id)

            if not head_path.exists():
                continue

            if not base_path.exists():
                self._missing_base.append(node_id)
                continue

            try:
                head_val = storage.deserialize(head_path)
                base_val = storage.deserialize(base_path)
                result = cmp_module.compare_values(head_val, base_val, node_id=node_id)
            except Exception as e:
                result = ComparisonResult(
                    equal=False,
                    report=f"Error during comparison: {e}",
                    node_id=node_id,
                )

            self._comparison_results.append(result)

        # --- CI reporting (non-failing) ---
        ci_module.emit_warnings(self._comparison_results)
        ci_module.emit_github_annotations(self._comparison_results)
        ci_module.write_github_step_summary(self._comparison_results, self._missing_base)
        ci_module.post_github_pr_comment(self._comparison_results, self._missing_base)
        ci_module.post_gitlab_mr_note(self._comparison_results, self._missing_base)
        ci_module.write_junit_xml(self._comparison_results, self._missing_base)

        # Clean up temp results dir
        try:
            shutil.rmtree(self.results_dir, ignore_errors=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Hook: print regression summary in terminal output
    # ------------------------------------------------------------------
    def pytest_terminal_summary(
        self, terminalreporter, exitstatus: int, config: pytest.Config
    ) -> None:
        if self.mode != "head":
            return

        if self._base_stderr and not self._comparison_results and not self._missing_base:
            # Only show error if we actually tried to compare something
            if self._head_node_ids:
                terminalreporter.write_sep("=", "DRIFT ERROR", red=True)
                terminalreporter.write_line(self._base_stderr)
            return

        if not self._comparison_results and not self._missing_base:
            return

        use_color = config.option.color != "no"
        summary = format_regression_summary(self._comparison_results, use_color=use_color)
        terminalreporter.write_line(summary)

        if self._missing_base:
            terminalreporter.write_sep("-", "Missing base-branch results")
            for node_id in self._missing_base:
                terminalreporter.write_line(
                    f"  WARNING: base branch did not produce a result for {node_id!r}"
                )

        if self._base_stderr and (not self._comparison_results or self._missing_base):
            # Only show stderr when it might explain missing results.
            terminalreporter.write_sep("-", "Base branch stderr (summary)")
            # Show just the first few lines, not full tracebacks.
            lines = self._base_stderr.strip().splitlines()
            error_lines = [l for l in lines if l.strip().startswith("ERROR") or l.strip().startswith("FAILED")]
            for line in (error_lines or lines)[:5]:
                terminalreporter.write_line(f"  {line.strip()}")

        # Highlight if any values changed (not a failure — may be intentional)
        any_drifted = any(not r.equal for r in self._comparison_results)
        if any_drifted:
            terminalreporter.write_sep("=", "DRIFTS DETECTED (review required)", yellow=True)


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--drift",
        metavar="BASE_BRANCH",
        default=None,
        help="Enable regression mode: compare test return values against BASE_BRANCH.",
    )


def pytest_configure(config: pytest.Config) -> None:
    # Determine mode and base branch
    mode = os.environ.get(_MODE_ENV)  # "base" when running as subprocess
    results_dir_env = os.environ.get(_RESULTS_DIR_ENV)

    if mode == "base":
        # Running as the base-branch subprocess
        if results_dir_env is None:
            return  # Misconfigured; bail silently
        results_dir = Path(results_dir_env)
        plugin = RegressionPlugin(
            base_branch="",  # not needed in base mode
            results_dir=results_dir,
            mode="base",
        )
        config.pluginmanager.register(plugin, "regression_plugin")
        config.addinivalue_line(
            "filterwarnings",
            "ignore::pytest.PytestReturnNotNoneWarning",
        )
        return

    # HEAD mode: check for --drift option or env var
    base_branch = config.getoption("--drift", default=None)
    if base_branch is None:
        base_branch = os.environ.get("PYTEST_DRIFT_BASE_BRANCH")

    if not base_branch:
        return  # Plugin not activated

    # Create temp results directory
    results_dir = Path(tempfile.mkdtemp(prefix="pytest_regression_"))
    (results_dir / "head").mkdir()
    (results_dir / "base").mkdir()

    plugin = RegressionPlugin(
        base_branch=base_branch,
        results_dir=results_dir,
        mode="head",
    )
    config.pluginmanager.register(plugin, "regression_plugin")
    config.addinivalue_line(
        "filterwarnings",
        "ignore::pytest.PytestReturnNotNoneWarning",
    )
