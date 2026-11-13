import datetime
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

from parrotlet import col, lit, select, table, val
from parrotlet import datatype as dt
from parrotlet import functions as F
from parrotlet.functions import spatial as ST
from parrotlet.functions import tables as TF

users = table("users")
u = users.c


@pytest.fixture
def geo() -> Iterator[duckdb.DuckDBPyConnection]:
    conn = duckdb.connect()
    conn.execute("LOAD spatial")
    yield conn
    conn.close()


def one(con: duckdb.DuckDBPyConnection, *exprs: object) -> tuple[object, ...]:
    row = select(*exprs).execute(con).fetchone()  # type: ignore[arg-type]
    assert row is not None
    return row


def test_scalar_functions(con: duckdb.DuckDBPyConnection) -> None:
    assert one(con, F.upper("abc"), F.length("héllo"), F.abs(-3), F.round(val(2.567), 2)) == ("ABC", 5, 3, 2.57)
    assert one(con, F.date_trunc("month", datetime.date(2026, 11, 13))) == (datetime.datetime(2026, 11, 1),)
    assert one(con, F.regexp_matches("abc", "b"), F.regexp_matches("ABC", "b", "i")) == (True, True)
    assert one(con, F.concat("a", 1, None)) == ("a1",)


def test_aggregate_functions(con: duckdb.DuckDBPyConnection) -> None:
    age = col("age", type_=dt.INTEGER)
    q = select(
        F.count(),
        F.count(u.dept, distinct=True),
        F.sum(age),
        F.avg(age),
        F.max(u.name),
        F.string_agg(u.name, ",", order_by=u.name),
        F.count().filter(u.dept == "eng"),
    ).from_(users)
    assert q.execute(con).fetchone() == (5, 2, 131, 32.75, "eve", "alice,bob,carol,dave,eve", 2)


def test_window_functions(con: duckdb.DuckDBPyConnection) -> None:
    q = (
        select(
            u.name,
            F.row_number().over(order_by=u.id),
            F.lag(u.name).over(order_by=u.id),
            F.lead(u.name, 2, "none").over(order_by=u.id),
            F.sum(u.id).over(order_by=u.id),
        )
        .from_(users)
        .order_by(u.id)
        .limit(2)
    )
    assert q.execute(con).fetchall() == [("alice", 1, None, "carol", 1), ("bob", 2, "alice", "dave", 3)]


def test_generic_functions(con: duckdb.DuckDBPyConnection) -> None:
    age = col("age", type_=dt.INTEGER)
    q = select(F.coalesce(age, 0), F.if_(age > 30, "old", "young"), F.greatest(age, 33)).from_(users).order_by(u.id)
    assert q.execute(con).fetchall()[:4] == [(30, "young", 33), (25, "young", 33), (41, "old", 41), (0, "young", 33)]


def test_lambda_functions(con: duckdb.DuckDBPyConnection) -> None:
    xs = F.list_value(lit(1), 2, 3)
    assert one(
        con,
        F.list_transform(xs, lambda x: x * 10),
        F.list_filter(xs, lambda x: x > 1),
        F.list_reduce(xs, lambda acc, x: acc + x),
        F.list_transform(xs, lambda x, i: x + i),
    ) == ([10, 20, 30], [2, 3], 6, [2, 4, 6])
    assert F.list_transform(xs, lambda x: x + 1).sql == 'list_transform(list_value(1, ?, ?), lambda "x": ("x" + ?))'


def test_struct_pack(con: duckdb.DuckDBPyConnection) -> None:
    assert one(con, F.struct_pack(a=1, b=F.upper("x"))) == ({"a": 1, "b": "X"},)


def test_table_functions(con: duckdb.DuckDBPyConnection) -> None:
    r = TF.range(1, 4).as_("r")
    assert select(r.c.range).from_(r).execute(con).fetchall() == [(1,), (2,), (3,)]
    s = TF.generate_series(datetime.date(2026, 1, 1), datetime.date(2026, 1, 3), datetime.timedelta(days=1)).as_("s")
    assert len(select().from_(s).execute(con).fetchall()) == 3


def test_table_function_named_options(con: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    path = (tmp_path / "x.csv").as_posix()
    con.execute(f"COPY (SELECT 1 AS a, 'x' AS b) TO '{path}'")
    q = select().from_(TF.read_csv(path, header=True, delim=","))
    assert '"header" := ?' in q.sql
    assert q.execute(con).fetchall() == [(1, "x")]


def test_spatial_functions(geo: duckdb.DuckDBPyConnection) -> None:
    a, b = ST.st_point(0, 0), ST.st_point(3, 4)
    assert one(geo, ST.st_distance(a, b), ST.st_as_text(b), ST.st_x(b)) == (5.0, "POINT (3 4)", 3.0)
    square = ST.st_geom_from_text("POLYGON((0 0, 2 0, 2 2, 0 2, 0 0))")
    assert one(geo, ST.st_area(square), ST.st_contains(square, ST.st_point(1, 1))) == (4.0, True)


def test_spatial_aggregate(geo: duckdb.DuckDBPyConnection) -> None:
    pts = TF.range(3).as_("t")
    q = select(ST.st_as_text(ST.st_extent_agg(ST.st_point(pts.c.range, pts.c.range)))).from_(pts)
    row = q.execute(geo).fetchone()
    assert row is not None
    assert str(row[0]).startswith("POLYGON")
