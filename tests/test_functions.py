import datetime
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

import parrotlet.functions as fn
import parrotlet.type as qlt
from parrotlet import col, lit, select, table, val

users = table("users")
u = users.c


@pytest.fixture
def geo() -> Iterator[duckdb.DuckDBPyConnection]:
    conn = duckdb.connect()
    conn.execute("LOAD spatial")
    yield conn
    conn.close()


def one(con: duckdb.DuckDBPyConnection, *exprs: object) -> tuple[object, ...]:
    row = select(*exprs).execute(con).fetchone()  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    assert row is not None
    return row


def test_scalar_functions(con: duckdb.DuckDBPyConnection) -> None:
    assert one(con, fn.upper("abc"), fn.length("héllo"), fn.abs(-3), fn.round(val(2.567), 2)) == ("ABC", 5, 3, 2.57)
    assert one(con, fn.date_trunc("month", datetime.date(2026, 11, 13))) == (datetime.datetime(2026, 11, 1),)
    assert one(con, fn.regexp_matches("abc", "b"), fn.regexp_matches("ABC", "b", "i")) == (True, True)
    assert one(con, fn.concat("a", 1, None)) == ("a1",)


def test_aggregate_functions(con: duckdb.DuckDBPyConnection) -> None:
    age = col("age", type_=qlt.Integer)
    q = select(
        fn.count(),
        fn.count(u.dept, distinct=True),
        fn.sum(age),
        fn.avg(age),
        fn.max(u.name),
        fn.string_agg(u.name, ",", order_by=u.name),
        fn.count().filter(u.dept == "eng"),
    ).from_(users)
    assert q.execute(con).fetchone() == (5, 2, 131, 32.75, "eve", "alice,bob,carol,dave,eve", 2)


def test_window_functions(con: duckdb.DuckDBPyConnection) -> None:
    q = (
        select(
            u.name,
            fn.row_number().over(order_by=u.id),
            fn.lag(u.name).over(order_by=u.id),
            fn.lead(u.name, 2, "none").over(order_by=u.id),
            fn.sum(u.id).over(order_by=u.id),
        )
        .from_(users)
        .order_by(u.id)
        .limit(2)
    )
    assert q.execute(con).fetchall() == [("alice", 1, None, "carol", 1), ("bob", 2, "alice", "dave", 3)]


def test_generic_functions(con: duckdb.DuckDBPyConnection) -> None:
    age = col("age", type_=qlt.Integer)
    q = select(fn.coalesce(age, 0), fn.if_(age > 30, "old", "young"), fn.greatest(age, 33)).from_(users).order_by(u.id)
    assert q.execute(con).fetchall()[:4] == [(30, "young", 33), (25, "young", 33), (41, "old", 41), (0, "young", 33)]


def test_lambda_functions(con: duckdb.DuckDBPyConnection) -> None:
    xs = fn.list_value(lit(1), 2, 3)
    assert one(
        con,
        fn.list_transform(xs, lambda x: x * 10),
        fn.list_filter(xs, lambda x: x > 1),
        fn.list_reduce(xs, lambda acc, x: acc + x),
        fn.list_transform(xs, lambda x, i: x + i),
    ) == ([10, 20, 30], [2, 3], 6, [2, 4, 6])
    assert fn.list_transform(xs, lambda x: x + 1).sql == 'list_transform(list_value(1, ?, ?), lambda "x": ("x" + ?))'


def test_struct_pack(con: duckdb.DuckDBPyConnection) -> None:
    assert one(con, fn.struct_pack(a=1, b=fn.upper("x"))) == ({"a": 1, "b": "X"},)


def test_table_functions(con: duckdb.DuckDBPyConnection) -> None:
    r = fn.table.range(1, 4).as_("r")
    assert select(r.c.range).from_(r).execute(con).fetchall() == [(1,), (2,), (3,)]
    s = fn.table.generate_series(datetime.date(2026, 1, 1), datetime.date(2026, 1, 3), datetime.timedelta(days=1)).as_(
        "s",
    )
    assert len(select().from_(s).execute(con).fetchall()) == 3


def test_table_function_named_options(con: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    path = (tmp_path / "x.csv").as_posix()
    con.execute(f"COPY (SELECT 1 AS a, 'x' AS b) TO '{path}'")
    q = select().from_(fn.table.read_csv(path, header=True, delim=","))
    assert '"header" := ?' in q.sql
    assert q.execute(con).fetchall() == [(1, "x")]


def test_spatial_functions(geo: duckdb.DuckDBPyConnection) -> None:
    a, b = fn.spatial.st_point(0, 0), fn.spatial.st_point(3, 4)
    assert one(geo, fn.spatial.st_distance(a, b), fn.spatial.st_as_text(b), fn.spatial.st_x(b)) == (
        5.0,
        "POINT (3 4)",
        3.0,
    )
    square = fn.spatial.st_geom_from_text("POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))")
    assert one(geo, fn.spatial.st_area(square), fn.spatial.st_contains(square, fn.spatial.st_point(1, 1))) == (
        4.0,
        True,
    )


def test_spatial_aggregate(geo: duckdb.DuckDBPyConnection) -> None:
    pts = fn.table.range(3).as_("t")
    q = select(fn.spatial.st_as_text(fn.spatial.st_extent_agg(fn.spatial.st_point(pts.c.range, pts.c.range)))).from_(
        pts,
    )
    row = q.execute(geo).fetchone()
    assert row is not None
    assert str(row[0]).startswith("POLYGON")
