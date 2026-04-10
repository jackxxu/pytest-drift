"""Tests for compare.py dispatch logic."""
import pytest

from pytest_drift.compare import compare_values


def test_equal_ints():
    result = compare_values(42, 42)
    assert result.equal


def test_different_ints():
    result = compare_values(42, 43)
    assert not result.equal
    assert "42" in result.report
    assert "43" in result.report


def test_equal_floats():
    result = compare_values(1.0000001, 1.0000002)
    assert result.equal  # within default tolerance


def test_different_floats():
    result = compare_values(1.0, 2.0)
    assert not result.equal


def test_nan_floats():
    result = compare_values(float("nan"), float("nan"))
    assert result.equal


def test_equal_strings():
    result = compare_values("hello", "hello")
    assert result.equal


def test_different_strings():
    result = compare_values("hello", "world")
    assert not result.equal


def test_equal_dicts():
    result = compare_values({"a": 1, "b": 2}, {"a": 1, "b": 2})
    assert result.equal


def test_different_dicts():
    result = compare_values({"a": 1}, {"a": 2})
    assert not result.equal
    assert "a" in result.report


def test_missing_key_in_base():
    result = compare_values({"a": 1, "b": 2}, {"a": 1})
    assert not result.equal


def test_equal_lists():
    result = compare_values([1, 2, 3], [1, 2, 3])
    assert result.equal


def test_different_lists():
    result = compare_values([1, 2, 3], [1, 2, 4])
    assert not result.equal


def test_different_list_lengths():
    result = compare_values([1, 2], [1, 2, 3])
    assert not result.equal
    assert "Length" in result.report


def test_equal_tuples():
    result = compare_values((1, "a"), (1, "a"))
    assert result.equal


def test_numpy_arrays_equal():
    import numpy as np

    result = compare_values(np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.0, 3.0]))
    assert result.equal


def test_numpy_arrays_close():
    import numpy as np

    result = compare_values(
        np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.0, 3.0 + 1e-7])
    )
    assert result.equal


def test_numpy_arrays_different():
    import numpy as np

    result = compare_values(np.array([1.0, 2.0]), np.array([1.0, 9.0]))
    assert not result.equal


def test_numpy_arrays_different_shape():
    import numpy as np

    result = compare_values(np.array([1, 2, 3]), np.array([1, 2]))
    assert not result.equal
    assert "Shape" in result.report


def test_type_mismatch():
    result = compare_values(42, "42")
    assert not result.equal


def test_node_id_propagated():
    result = compare_values(1, 2, node_id="test_foo::test_bar")
    assert result.node_id == "test_foo::test_bar"


def test_dataframe_comparison():
    pytest.importorskip("pandas")
    import pandas as pd

    df1 = pd.DataFrame({"id": [1, 2], "v": [10, 20]})
    df2 = pd.DataFrame({"id": [1, 2], "v": [10, 20]})
    result = compare_values(df1, df2)
    assert result.equal
