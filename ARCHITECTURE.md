# pytest-drift Architecture

## Module overview

| Module | Responsibility |
|---|---|
| `plugin.py` | pytest hooks, orchestration, plugin registration |
| `runner.py` | git worktree management, base-branch subprocess |
| `storage.py` | serialize/deserialize test return values |
| `compare.py` | type-dispatching value comparison |
| `pandas_utils.py` | DataFrame/Series comparison, `ComparisonResult` dataclass |
| `report.py` | terminal diff formatting |
| `ci.py` | CI-specific reporters (warnings, GitHub Actions, GitLab CI) |

---

## Architecture diagram

```mermaid
flowchart TD
    subgraph USER["User / CI invocation"]
        CMD["pytest --drift &lt;base-branch&gt;"]
    end

    subgraph PLUGIN["plugin.py · RegressionPlugin"]
        direction TB
        CFG["pytest_configure
        ─────────────────
        Parse --drift / env vars
        Create temp results_dir/
          head/  base/
        Register plugin"]

        COL["pytest_collection_finish
        ─────────────────
        Capture collected node IDs
        Spawn base-branch run
        in background thread"]

        WRAP["pytest_pyfunc_call  (wrapper)
        ─────────────────
        Intercept each test's
        return value
        → serialize to results_dir/head/"]

        FIN["pytest_sessionfinish
        ─────────────────
        Join background thread
        For each head result:
          compare head vs base
        Call CI reporters
        Clean up temp dirs"]

        TERM["pytest_terminal_summary
        ─────────────────
        Print drift summary table
        Show DRIFTED (yellow)
        vs STABLE (green)"]

        CFG --> COL --> WRAP --> FIN --> TERM
    end

    subgraph BASE["Base-branch subprocess  (mode=base)"]
        direction TB
        WM["runner.py · WorktreeManager
        ─────────────────
        git worktree add &lt;branch&gt;
        → temp dir"]
        BP["runner.py · run_base_branch
        ─────────────────
        spawn: python -m pytest
          PYTEST_DRIFT_MODE=base
          PYTEST_DRIFT_RESULTS_DIR=...
        (same node IDs, no recursion)"]
        BW["pytest_pyfunc_call  (base mode)
        ─────────────────
        Capture return values
        → serialize to results_dir/base/"]
        WM --> BP --> BW
    end

    subgraph STORAGE["storage.py"]
        SER["serialize(obj, path)
        ─────────────────
        pd.DataFrame/Series → .parquet
        everything else → cloudpickle .pkl"]
        DE["deserialize(path)
        ─────────────────
        Detect marker → parquet
        or cloudpickle load"]
    end

    subgraph COMPARE["compare.py + pandas_utils.py"]
        DISP["compare_values(head, base)
        ─────────────────
        Dispatches by type:
          DataFrame/Series → datacompy
          ndarray → np.testing
          float → math.isclose
          dict/list → recursive
          generic → ==
        → ComparisonResult(equal, report)"]
    end

    subgraph CI["ci.py · CI reporters"]
        W["emit_warnings()
        ─────────────────
        warnings.warn(DriftWarning)
        → pytest warnings summary"]
        GHA["emit_github_annotations()
        ─────────────────
        GITHUB_ACTIONS=true
        → ::warning:: stdout lines
           (PR inline annotations)"]
        SUM["write_github_step_summary()
        ─────────────────
        GITHUB_STEP_SUMMARY file
        → markdown table on
           Actions run page"]
        JU["write_junit_xml()
        ─────────────────
        GITLAB_CI=true
        → drift-report.xml
           (MR test widget)"]
    end

    CMD --> PLUGIN
    COL -- "background thread" --> BASE
    BASE -- "results_dir/base/" --> STORAGE
    WRAP -- "results_dir/head/" --> STORAGE
    FIN -- "load head + base results" --> STORAGE
    STORAGE --> COMPARE
    COMPARE -- "ComparisonResult[]" --> FIN
    FIN --> CI
```

---

## Runtime flow

```
pytest --drift main
        │
        ├─ [collection] ──────────────────────────────────────────────────────┐
        │   Collect all test node IDs                                          │ background thread
        │                                                                      ▼
        │                                                         git worktree add main /tmp/wt
        │                                                         python -m pytest (base mode)
        │                                                           └─ captures return values
        │                                                               → results_dir/base/
        │
        ├─ [test run] (HEAD)
        │   Each test runs normally.
        │   Wrapper intercepts return value → serialize → results_dir/head/
        │   Test pass/fail is UNCHANGED — drift doesn't affect it.
        │
        └─ [session finish]
            Join background thread (wait for base run)
            For each test with a head result:
              deserialize head + base → compare_values() → ComparisonResult
            ──────────────────────────────────────────────────────────────────
            CI reporters (non-failing):
              DriftWarning        → pytest warnings summary (universal)
              ::warning::         → GitHub PR annotations
              GITHUB_STEP_SUMMARY → markdown report on Actions run page
              drift-report.xml    → GitLab MR test widget
            ──────────────────────────────────────────────────────────────────
            Terminal: STABLE (green) / DRIFTED (yellow) per test
```

---

## Key design decisions

**Tests never fail due to drift.** The exit code is never modified. Drift is purely observational — it surfaces changed return values for review without blocking CI.

**Base branch runs in a throw-away git worktree.** `git worktree add` checks out the base branch into a temp directory without touching the working tree. It is cleaned up after the session regardless of outcome.

**Serialization is type-aware.** DataFrames and Series use Parquet (preserving dtypes); everything else uses cloudpickle. A small marker file (`__parquet__` / `__parquet_series__`) tells the deserializer which path to take.

**Comparison dispatches by type.** DataFrames go through datacompy (with positional fallback to `pd.testing`), numpy arrays through `np.testing`, floats through `math.isclose`, and dicts/lists recursively. This avoids false positives from floating-point noise.

**CI reporting is layered.** Each reporter is independent and fires only when its environment is detected, so the same plugin works locally, on GitHub Actions, and on GitLab CI without configuration.
