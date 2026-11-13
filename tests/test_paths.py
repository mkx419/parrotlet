"""Everything that takes a file path also accepts `pathlib.Path`."""

from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

import parrotlet.functions as fn
from parrotlet import (
    Database,
    attach,
    copy_from,
    copy_to,
    detach,
    export_database,
    file,
    import_database,
    lit,
    select,
    table,
)
from parrotlet.query import param, path_str, render_literal


def test_path_str() -> None:
    assert path_str("data/x.csv") == "data/x.csv"
    assert path_str(PurePosixPath("data/x.csv")) == "data/x.csv"
    assert path_str(PureWindowsPath(r"C:\data\x.csv")) == "C:/data/x.csv"  # forward slashes on every platform
    assert render_literal(PurePosixPath("it's.csv")) == "'it''s.csv'"


def test_param_sends_paths_as_str() -> None:
    assert param(PurePosixPath("a.csv")).params == ("a.csv",)
    assert param([PurePosixPath("a.csv"), "b.csv"]).params == (["a.csv", "b.csv"],)


def test_database_file(tmp_path: Path) -> None:
    path = tmp_path / "app.duckdb"
    with Database(path) as db:
        db.execute(select(lit(1).as_("x")))
    assert path.exists()


def test_copy_file_and_table_functions(tmp_path: Path) -> None:
    db = Database()
    db.sql(t"CREATE TABLE t AS SELECT * FROM range(3) r(n)")
    out = tmp_path / "t.parquet"
    db.execute(copy_to("t", out, format="parquet"))
    assert out.exists()

    assert db.from_(file(out)).fetchall() == [(0,), (1,), (2,)]
    assert db.from_(fn.table.read_parquet(out)).fetchall() == [(0,), (1,), (2,)]
    assert db.from_(fn.table.read_parquet([out, out])).fetchall() == [(0,), (1,), (2,)] * 2
    assert db.select(fn.count()).from_(fn.table.glob(tmp_path / "*.parquet")).fetchall() == [(1,)]

    db.sql(t"CREATE TABLE u (n BIGINT)")
    db.execute(copy_from("u", out, format="parquet"))
    assert db.select(fn.count()).from_(table("u")).fetchall() == [(3,)]


def test_attach_export_import(tmp_path: Path) -> None:
    db = Database()
    db.execute(attach(tmp_path / "other.db", "other"))
    db.sql(t"CREATE TABLE other.main.t AS SELECT 42 AS v")
    db.execute(detach("other"))

    db.execute(attach(tmp_path / "other.db", "other2", read_only=True))
    assert db.from_(table("t", catalog="other2")).fetchall() == [(42,)]

    db.sql(t"CREATE TABLE x AS SELECT 1 AS a")
    db.execute(export_database(tmp_path / "dump"))
    fresh = Database()
    fresh.execute(import_database(tmp_path / "dump"))
    assert fresh.from_("x").fetchall() == [(1,)]


def test_bytes_paths_are_rejected() -> None:
    class BytesPath:
        def __fspath__(self) -> bytes:
            return b"x.csv"

    with pytest.raises(TypeError, match="str path"):
        path_str(BytesPath())  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
