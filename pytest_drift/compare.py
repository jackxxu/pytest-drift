"""Type-dispatching comparison logic for test return values."""
from __future__ import annotations

import math
from typing import Any

from .pandas_utils import ComparisonResult, compare_dataframes, compare_series


def compare_values(head: Any, base: Any, node_id: str = "") -> ComparisonResult:
    """
    Compare head (current branch) and base (base branch) return values.
    Dispatches based on type.
    """
    result = _dispatch(head, base)
    result.node_id = node_id
    return result


def _dispatch(head: Any, base: Any) -> ComparisonResult:
    # Check pandas types first (before generic checks)
    try:
        import pandas as pd

        if isinstance(head, pd.DataFrame) and isinstance(base, pd.DataFrame):
            return compare_dataframes(head, base)
        if isinstance(head, pd.Series) and isinstance(base, pd.Series):
            return compare_series(head, base)
        if isinstance(head, (pd.DataFrame, pd.Series)) or isinstance(
            base, (pd.DataFrame, pd.Series)
        ):
            return ComparisonResult(
                equal=False,
                report=f"Type mismatch: head={type(head).__name__}, base={type(base).__name__}",
            )
    except ImportError:
        pass

    # numpy arrays
    try:
        import numpy as np

        if isinstance(head, np.ndarray) and isinstance(base, np.ndarray):
            return _compare_arrays(head, base)
    except ImportError:
        pass

    # float scalars
    if isinstance(head, float) and isinstance(base, float):
        return _compare_floats(head, base)

    # numpy scalars that are float-like
    try:
        import numpy as np

        if isinstance(head, np.floating) and isinstance(base, np.floating):
            return _compare_floats(float(head), float(base))
    except ImportError:
        pass

    # dict
    if isinstance(head, dict) and isinstance(base, dict):
        return _compare_dicts(head, base)

    # list / tuple
    if isinstance(head, (list, tuple)) and isinstance(base, (list, tuple)):
        return _compare_sequences(head, base)

    # generic fallback
    return _compare_generic(head, base)


def _compare_floats(head: float, base: float, rtol: float = 1e-5, atol: float = 1e-8) -> ComparisonResult:
    if math.isnan(head) and math.isnan(base):
        return ComparisonResult(equal=True, report=None)
    equal = math.isclose(head, base, rel_tol=rtol, abs_tol=atol)
    report = None if equal else f"Float mismatch: head={head!r}, base={base!r}"
    return ComparisonResult(equal=equal, report=report)


def _compare_arrays(head, base) -> ComparisonResult:
    import numpy as np

    if head.shape != base.shape:
        return ComparisonResult(
            equal=False,
            report=f"Shape mismatch: head={head.shape}, base={base.shape}",
        )
    try:
        np.testing.assert_array_almost_equal(head, base, decimal=5)
        return ComparisonResult(equal=True, report=None)
    except AssertionError as e:
        return ComparisonResult(equal=False, report=str(e))


def _compare_dicts(head: dict, base: dict) -> ComparisonResult:
    head_keys = set(head.keys())
    base_keys = set(base.keys())

    if head_keys != base_keys:
        only_head = head_keys - base_keys
        only_base = base_keys - head_keys
        parts = []
        if only_head:
            parts.append(f"Keys only in head: {sorted(str(k) for k in only_head)}")
        if only_base:
            parts.append(f"Keys only in base: {sorted(str(k) for k in only_base)}")
        return ComparisonResult(equal=False, report="\n".join(parts))

    mismatches = []
    for key in sorted(head_keys, key=str):
        sub = _dispatch(head[key], base[key])
        if not sub.equal:
            mismatches.append(f"  Key {key!r}: {sub.report}")

    if mismatches:
        return ComparisonResult(
            equal=False, report="Dict mismatches:\n" + "\n".join(mismatches)
        )
    return ComparisonResult(equal=True, report=None)


def _compare_sequences(head, base) -> ComparisonResult:
    if len(head) != len(base):
        return ComparisonResult(
            equal=False,
            report=f"Length mismatch: head={len(head)}, base={len(base)}",
        )
    mismatches = []
    for i, (h, b) in enumerate(zip(head, base)):
        sub = _dispatch(h, b)
        if not sub.equal:
            mismatches.append(f"  Index {i}: {sub.report}")
    if mismatches:
        return ComparisonResult(
            equal=False,
            report=f"{type(head).__name__} mismatches:\n" + "\n".join(mismatches),
        )
    return ComparisonResult(equal=True, report=None)


def _compare_generic(head: Any, base: Any) -> ComparisonResult:
    try:
        equal = bool(head == base)
    except Exception:
        equal = False

    if equal:
        return ComparisonResult(equal=True, report=None)

    return ComparisonResult(
        equal=False,
        report=f"Value mismatch:\n  head: {head!r}\n  base: {base!r}",
    )
