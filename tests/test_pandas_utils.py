"""Tests for pandas_utils.py index detection and comparison."""
import pytest

pd = pytest.importorskip("pandas")
import pandas as pd

from pytest_drift.pandas_utils import (
    compare_dataframes,
    compare_series,
    detect_index_columns,
)


def test_detect_named_index():
    df = pd.DataFrame({"val": [1, 2, 3]}, index=pd.Index([10, 20, 30], name="row_id"))
    result = detect_index_columns(df)
    assert result == ["row_id"]


def test_detect_multiindex():
    idx = pd.MultiIndex.from_tuples([(1, "a"), (1, "b"), (2, "a")], names=["x", "y"])
    df = pd.DataFrame({"val": [1, 2, 3]}, index=idx)
    result = detect_index_columns(df)
    assert result == ["x", "y"]


def test_detect_single_unique_column():
    df = pd.DataFrame({"id": [1, 2, 3], "value": [10.0, 20.0, 30.0]})
    result = detect_index_columns(df)
    assert result == ["id"]


def test_detect_composite_key():
    df = pd.DataFrame(
        {
            "year": [2020, 2020, 2021, 2021],
            "month": [1, 2, 1, 2],
            "value": [1.0, 2.0, 3.0, 4.0],
        }
    )
    result = detect_index_columns(df)
    assert set(result) == {"year", "month"}


def test_detect_avoids_float_columns():
    df = pd.DataFrame(
        {
            "float_id": [1.0, 2.0, 3.0],  # float, unique — but should be deprioritized
            "str_id": ["a", "b", "c"],
        }
    )
    result = detect_index_columns(df)
    # Should prefer str_id over float_id
    assert result == ["str_id"]


def test_detect_no_unique_key():
    df = pd.DataFrame({"a": [1, 1, 2], "b": [1, 1, 2]})
    result = detect_index_columns(df)
    assert result is None


def test_detect_empty_dataframe():
    df = pd.DataFrame({"id": pd.Series([], dtype=int), "val": pd.Series([], dtype=float)})
    result = detect_index_columns(df)
    assert result is None


def test_compare_dataframes_equal():
    df1 = pd.DataFrame({"id": [1, 2], "val": [10.0, 20.0]})
    df2 = pd.DataFrame({"id": [1, 2], "val": [10.0, 20.0]})
    result = compare_dataframes(df1, df2)
    assert result.equal


def test_compare_dataframes_different_values():
    df1 = pd.DataFrame({"id": [1, 2], "val": [10.0, 20.0]})
    df2 = pd.DataFrame({"id": [1, 2], "val": [10.0, 99.0]})
    result = compare_dataframes(df1, df2)
    assert not result.equal
    assert result.report is not None


def test_compare_dataframes_different_rows():
    df1 = pd.DataFrame({"id": [1, 2, 3], "val": [10.0, 20.0, 30.0]})
    df2 = pd.DataFrame({"id": [1, 2], "val": [10.0, 20.0]})
    result = compare_dataframes(df1, df2)
    assert not result.equal


def test_compare_dataframes_out_of_order():
    df1 = pd.DataFrame({"id": [1, 2, 3], "val": [10.0, 20.0, 30.0]})
    df2 = pd.DataFrame({"id": [3, 1, 2], "val": [30.0, 10.0, 20.0]})
    result = compare_dataframes(df1, df2)
    assert result.equal


def test_compare_series_equal():
    s1 = pd.Series([1, 2, 3], name="x")
    s2 = pd.Series([1, 2, 3], name="x")
    result = compare_series(s1, s2)
    assert result.equal


def test_compare_series_different():
    s1 = pd.Series([1, 2, 3], name="x")
    s2 = pd.Series([1, 2, 99], name="x")
    result = compare_series(s1, s2)
    assert not result.equal
