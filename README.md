# pytest-drift

A pytest plugin for regression testing via branch comparison. When a test returns a value, the plugin runs the same test on a base git branch and compares the results — catching regressions before they merge.

## How it works

1. You run `pytest --drift BASE_BRANCH`
2. For every test that **returns a non-None value**, the plugin:
   - Records the return value from the current branch (HEAD)
   - Simultaneously runs the same tests on `BASE_BRANCH` in a git worktree
   - Compares the two results at the end of the session
3. Tests returning `None` (the default for normal pytest tests) are ignored entirely

The base branch runs in parallel with your HEAD tests, so total wall time is approximately `max(HEAD_time, BASE_time)` rather than `HEAD_time + BASE_time`.

## Installation

```bash
pip install pytest-drift

# With smart DataFrame diff reports (recommended):
pip install "pytest-drift[datacompy]"
```

## Usage

### CLI flag

```bash
pytest --drift main
pytest --drift origin/main
```

### Environment variable

```bash
export PYTEST_DRIFT_BASE_BRANCH=main
pytest
```

## Writing regression tests

Return a value from your test — that's it:

```python
def test_revenue_calculation():
    df = compute_revenue(load_data())
    return df  # compared against the same function on BASE_BRANCH

def test_model_accuracy():
    return evaluate_model()  # compared as a float

def test_pipeline_output():
    return run_pipeline()  # compared as a dict, list, DataFrame, etc.
```

Normal tests (returning `None`) are unaffected and run as usual.

## Comparison logic

The plugin dispatches comparison based on the return type:

| Type | Comparison method |
|---|---|
| `pd.DataFrame` | Auto-detects join columns; uses `datacompy` if installed, else `pd.testing.assert_frame_equal` |
| `pd.Series` | Converted to DataFrame, same path as above |
| `float` / `np.floating` | `math.isclose` with `rtol=1e-5, atol=1e-8` |
| `np.ndarray` | `np.testing.assert_array_almost_equal` (5 decimal places) |
| `dict` | Recursive key-by-key comparison |
| `list` / `tuple` | Element-wise comparison |
| Everything else | `==`, with `repr()` diff on failure |

### Pandas index auto-detection

When comparing DataFrames, the plugin automatically finds the best join key:

1. **Named index**: if the DataFrame already has a named (non-RangeIndex) index, it's used directly
2. **MultiIndex**: all named index levels are used
3. **Column heuristic**: searches combinations of up to 3 non-float columns with full cardinality (every row is unique in that combination)
4. **Positional fallback**: if no unique key is found, rows are compared positionally

You can also pass `join_columns` explicitly by calling `compare_dataframes` directly from `pandas_utils`.

## Terminal output

At the end of the session a regression summary is printed:

```
========================================================================
REGRESSION COMPARISON SUMMARY
========================================================================
PASSED tests/test_revenue.py::test_revenue_calculation
FAILED tests/test_model.py::test_model_accuracy
    Float mismatch:
      head: 0.923
      base: 0.941
------------------------------------------------------------------------
1 passed, 1 failed (2 total regression comparisons)
```

## How branch switching works

The plugin uses `git worktree add` to check out `BASE_BRANCH` into a temporary directory — your working tree is never touched. The worktree is cleaned up automatically after the session.

```
HEAD tests run         ─────────────────────────▶  sessionfinish
                                                       │
git worktree add ──▶  BASE tests run in parallel  ────┘  compare
```

## Requirements

| Package | Required | Purpose |
|---|---|---|
| `pytest >= 7.0` | Yes | Core |
| `cloudpickle >= 3.0` | Yes | Serialization of return values |
| `pandas >= 1.5` | Yes | DataFrame/Series support |
| `datacompy >= 0.9` | Optional | Rich DataFrame diff reports |
| `pyarrow >= 10.0` | Optional | Parquet storage for large DataFrames |

## Comparison with similar tools

| | pytest-drift | syrupy / pytest-snapshot | pytest-regressions |
|---|---|---|---|
| Baseline source | git branch (live re-run) | committed snapshot file | committed YAML/CSV file |
| Baseline stays fresh | yes — base branch always re-runs | only when you update snapshots | only when you update fixtures |
| Detects environment drift | yes — same code path, different branch | no | no |
| Test changes required | no — just `return` a value | yes — use a snapshot fixture | yes — use a regression fixture |
| DataFrame support | yes, with datacompy | via custom serializer | yes, via `dataframe_regression` |

**When to use pytest-drift** — you want to catch regressions introduced by your current branch without manually maintaining baseline files. Ideal for data pipelines, model outputs, or any function whose output is hard to specify upfront but easy to compare.

**When to use snapshot tools** — you want a stable, reviewable artifact in version control. Snapshots are better when the baseline should be human-readable or when you're not working in a git-branch workflow.

## Caveats

- The base branch subprocess uses the same Python environment as HEAD — if your project uses `tox` or `nox`, point to the correct environment
- Session-scoped fixtures with side effects (e.g. starting a server) will run twice — once per session
- Tests that fail on HEAD are not compared (no base result is fetched for them)
- Tests that fail on BASE produce a "base branch test failed, cannot compare" warning
