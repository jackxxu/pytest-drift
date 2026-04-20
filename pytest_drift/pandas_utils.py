"""Pandas DataFrame/Series index auto-detection and comparison."""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class ComparisonResult:
    equal: bool
    report: str | None
    node_id: str = ""
    extra: dict = field(default_factory=dict)


def detect_index_columns(df: "pd.DataFrame", max_combo_size: int = 3) -> list[str] | None:
    """
    Auto-detect which columns can serve as join keys for comparison.

    Priority:
    1. Named non-RangeIndex (already set as index)
    2. Heuristic: find smallest combo of non-float cols with full cardinality
    3. None → fall back to positional comparison
    """
    import pandas as pd

    # Case A: already has a meaningful named index
    if not isinstance(df.index, pd.RangeIndex):
        if isinstance(df.index, pd.MultiIndex):
            if all(name is not None for name in df.index.names):
                return list(df.index.names)
        elif df.index.name is not None:
            return [df.index.name]

    n = len(df)
    if n == 0 or len(df.columns) == 0:
        return None

    # Case B: heuristic column search (exclude float columns — poor join keys)
    candidate_cols = [
        c for c in df.columns if not pd.api.types.is_float_dtype(df[c].dtype)
    ]
    # Sort by cardinality descending (higher = better key candidate)
    candidate_cols = sorted(candidate_cols, key=lambda c: df[c].nunique(), reverse=True)

    for r in range(1, min(max_combo_size + 1, len(candidate_cols) + 1)):
        for combo in itertools.combinations(candidate_cols, r):
            try:
                if df.groupby(list(combo)).ngroups == n:
                    return list(combo)
            except Exception:
                continue

    return None


def _reset_named_index(df: "pd.DataFrame") -> "pd.DataFrame":
    """If df has a named index, reset it to columns."""
    import pandas as pd

    if not isinstance(df.index, pd.RangeIndex):
        return df.reset_index()
    return df


def compare_dataframes(
    head_df: "pd.DataFrame",
    base_df: "pd.DataFrame",
    join_columns: list[str] | None = None,
) -> ComparisonResult:
    """Compare two DataFrames, auto-detecting join columns if not provided."""
    import pandas as pd

    head_flat = _reset_named_index(head_df)
    base_flat = _reset_named_index(base_df)

    if join_columns is None:
        join_columns = detect_index_columns(head_flat)

    # Try datacompy first
    try:
        # mask unnecessary warnings 
        import logging as _logging
        for _lg in ("datacompy.fugue", "datacompy.snowflake", "datacompy.spark.sql"):
            _logging.getLogger(_lg).setLevel(_logging.ERROR)
        import datacompy

        if not hasattr(datacompy, "Compare"):
            raise ImportError("datacompy.Compare not available")

        if join_columns is None:
            # No key found; use all columns positionally by adding a row-number key
            head_flat = head_flat.copy()
            base_flat = base_flat.copy()
            head_flat["__row__"] = range(len(head_flat))
            base_flat["__row__"] = range(len(base_flat))
            join_columns = ["__row__"]

        cmp = datacompy.Compare(
            head_flat,
            base_flat,
            join_columns=join_columns,
            df1_name="head",
            df2_name="base",
            abs_tol=1e-8,
            rel_tol=1e-5,
        )
        equal = cmp.matches()
        return ComparisonResult(
            equal=equal,
            report=None if equal else cmp.report(),
        )
    except ImportError:
        pass

    # Fallback: pd.testing.assert_frame_equal
    try:
        if join_columns:
            head_sorted = head_flat.set_index(join_columns).sort_index()
            base_sorted = base_flat.set_index(join_columns).sort_index()
        else:
            head_sorted = head_flat.reset_index(drop=True)
            base_sorted = base_flat.reset_index(drop=True)

        pd.testing.assert_frame_equal(
            head_sorted, base_sorted, check_like=True, rtol=1e-5
        )
        return ComparisonResult(equal=True, report=None)
    except AssertionError as e:
        return ComparisonResult(equal=False, report=str(e))


def compare_series(head_s: "pd.Series", base_s: "pd.Series") -> ComparisonResult:
    """Compare two Series by converting to DataFrames."""
    head_df = head_s.to_frame(name=head_s.name or "value")
    base_df = base_s.to_frame(name=base_s.name or "value")
    return compare_dataframes(head_df, base_df)
