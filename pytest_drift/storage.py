"""Serialization and deserialization of test return values."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _node_id_to_filename(node_id: str, suffix: str) -> str:
    h = hashlib.md5(node_id.encode()).hexdigest()
    return f"{h}{suffix}"


def make_result_path(results_dir: Path, mode: str, node_id: str) -> Path:
    """Return the path where a result for node_id should be stored."""
    # Try parquet path for DataFrames (determined at write time)
    return results_dir / mode / _node_id_to_filename(node_id, ".pkl")


def make_parquet_path(results_dir: Path, mode: str, node_id: str) -> Path:
    return results_dir / mode / _node_id_to_filename(node_id, ".parquet")


def serialize(obj: Any, path: Path) -> None:
    """Serialize obj to path. Uses parquet for DataFrames if pyarrow is available."""
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import pandas as pd

        if isinstance(obj, pd.DataFrame):
            parquet_path = path.with_suffix(".parquet")
            try:
                obj.to_parquet(parquet_path)
                # Write a small marker so deserialize knows to use parquet
                path.write_bytes(b"__parquet__")
                return
            except Exception:
                pass  # Fall through to cloudpickle
        elif isinstance(obj, pd.Series):
            parquet_path = path.with_suffix(".parquet")
            try:
                obj.to_frame().to_parquet(parquet_path)
                path.write_bytes(b"__parquet_series__")
                return
            except Exception:
                pass
    except ImportError:
        pass

    import cloudpickle

    path.write_bytes(cloudpickle.dumps(obj))


def deserialize(path: Path) -> Any:
    """Deserialize obj from path."""
    data = path.read_bytes()

    if data in (b"__parquet__", b"__parquet_series__"):
        import pandas as pd

        parquet_path = path.with_suffix(".parquet")
        try:
            df = pd.read_parquet(parquet_path)
        except TypeError:
            # Parquet files store pandas metadata including original column-index
            # dtypes. pyarrow tries to cast back to e.g. datetime64[D] which
            # pandas >= 2.0 rejects.  Re-read without pandas metadata to avoid.
            import pyarrow.parquet as pq
            table = pq.read_table(parquet_path)
            table = table.replace_schema_metadata({})
            df = table.to_pandas()

        if data == b"__parquet_series__":
            col = df.columns[0]
            return df[col]
        return df

    import cloudpickle

    return cloudpickle.loads(data)


def write_manifest(results_dir: Path, mode: str, manifest: dict[str, str]) -> None:
    """Write a JSON manifest mapping node_id -> filename."""
    manifest_path = results_dir / mode / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))


def read_manifest(results_dir: Path, mode: str) -> dict[str, str]:
    """Read the JSON manifest for a mode. Returns empty dict if missing."""
    manifest_path = results_dir / mode / "manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text())
