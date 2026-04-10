"""Tests for storage.py serialization/deserialization."""
import pytest


def test_roundtrip_scalar(tmp_path):
    from pytest_drift.storage import deserialize, make_result_path, serialize

    path = make_result_path(tmp_path, "head", "test_foo::test_bar")
    serialize(42, path)
    assert deserialize(path) == 42


def test_roundtrip_float(tmp_path):
    from pytest_drift.storage import deserialize, make_result_path, serialize

    path = make_result_path(tmp_path, "head", "test_foo::test_float")
    serialize(3.14, path)
    assert abs(deserialize(path) - 3.14) < 1e-10


def test_roundtrip_dict(tmp_path):
    from pytest_drift.storage import deserialize, make_result_path, serialize

    obj = {"a": 1, "b": [2, 3], "c": {"d": 4}}
    path = make_result_path(tmp_path, "head", "test_foo::test_dict")
    serialize(obj, path)
    assert deserialize(path) == obj


def test_roundtrip_list(tmp_path):
    from pytest_drift.storage import deserialize, make_result_path, serialize

    obj = [1, "two", 3.0, None]
    path = make_result_path(tmp_path, "head", "test_foo::test_list")
    serialize(obj, path)
    assert deserialize(path) == obj


def test_roundtrip_dataframe(tmp_path):
    import pandas as pd

    from pytest_drift.storage import deserialize, make_result_path, serialize

    df = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
    path = make_result_path(tmp_path, "head", "test_foo::test_df")
    serialize(df, path)
    result = deserialize(path)
    pd.testing.assert_frame_equal(df, result)


def test_different_nodeids_produce_different_paths(tmp_path):
    from pytest_drift.storage import make_result_path

    path1 = make_result_path(tmp_path, "head", "test_foo::test_a")
    path2 = make_result_path(tmp_path, "head", "test_foo::test_b")
    assert path1 != path2


def test_same_nodeid_produces_same_path(tmp_path):
    from pytest_drift.storage import make_result_path

    path1 = make_result_path(tmp_path, "head", "test_foo::test_a[param-1]")
    path2 = make_result_path(tmp_path, "head", "test_foo::test_a[param-1]")
    assert path1 == path2


def test_manifest_roundtrip(tmp_path):
    from pytest_drift.storage import read_manifest, write_manifest

    manifest = {"test_foo::test_a": "abc123.pkl", "test_foo::test_b": "def456.pkl"}
    write_manifest(tmp_path, "head", manifest)
    result = read_manifest(tmp_path, "head")
    assert result == manifest


def test_manifest_missing(tmp_path):
    from pytest_drift.storage import read_manifest

    assert read_manifest(tmp_path, "head") == {}
