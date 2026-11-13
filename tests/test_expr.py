import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import duckdb
import pytest

import parrotlet.type as qlt
from parrotlet import (
    Expr,
    and_,
    case,
    cast,
    col,
    exists,
    func,
    lit,
    or_,
    rows_between,
    select,
    sql,
    star,
    table,
    val,
    window,
)
from parrotlet.query import render_literal

users = table("users")
u = users.c


def scalar(con: duckdb.DuckDBPyConnection, expr: Expr[Any]) -> object:
    row = select(expr).execute(con).fetchone()
    assert row is not None
    return row[0]


def test_column_quoting() -> None:
    assert col("a").sql == '"a"'
    assert col('we"ird', "t").sql == '"t"."we""ird"'
    assert table("t", schema="s").c.x.sql == '"s"."t"."x"'
    assert table("t").as_("x").c.y.sql == '"x"."y"'


def test_comparison_and_logic() -> None:
    e = (u.age >= 20) & ((u.name == "bob") | ~(u.dept != "eng"))
    q = e.build()
    assert q.sql == '(("users"."age" >= ?) AND (("users"."name" = ?) OR (NOT ("users"."dept" <> ?))))'
    assert q.params == (20, "bob", "eng")


def test_eq_none_is_null() -> None:
    assert (u.age == None).sql == '("users"."age" IS NULL)'  # noqa: E711
    assert (u.age != None).sql == '("users"."age" IS NOT NULL)'  # noqa: E711


def test_expr_has_no_truth_value() -> None:
    with pytest.raises(TypeError):
        bool(u.age > 1)


def test_arithmetic_with_reversed_operands(con: duckdb.DuckDBPyConnection) -> None:
    assert scalar(con, 10 - val(3) * 2) == 4
    assert scalar(con, val(7) // 2) == 3
    assert scalar(con, val(7) % 4) == 3
    assert scalar(con, -val(5)) == -5
    assert scalar(con, val("a").concat("b")) == "ab"


def test_in_between_like(con: duckdb.DuckDBPyConnection) -> None:
    q = select(u.name).from_(users).where(u.id.in_([1, 3]), u.age.between(20, 40), u.name.like("a%")).order_by(u.id)
    assert q.execute(con).fetchall() == [("alice",)]
    assert select(u.name).from_(users).where(u.name.ilike("B%")).execute(con).fetchall() == [("bob",)]
    assert select(func.count()).from_(users).where(u.id.not_in([1, 2])).execute(con).fetchone() == (3,)


def test_in_empty_list(con: duckdb.DuckDBPyConnection) -> None:
    assert select(func.count()).from_(users).where(u.id.in_([])).execute(con).fetchone() == (0,)
    assert select(func.count()).from_(users).where(u.id.not_in([])).execute(con).fetchone() == (5,)


def test_in_rejects_string() -> None:
    with pytest.raises(TypeError):
        u.name.in_("abc")


def test_in_subquery(con: duckdb.DuckDBPyConnection) -> None:
    orders = table("orders")
    q = select(u.name).from_(users).where(u.id.in_(select(orders.c.user_id).from_(orders))).order_by(u.name)
    assert q.execute(con).fetchall() == [("alice",), ("bob",), ("carol",)]


def test_exists(con: duckdb.DuckDBPyConnection) -> None:
    o = table("orders").as_("o")
    q = select(u.name).from_(users).where(exists(select(1).from_(o).where(o.c.user_id == u.id, o.c.amount > 500)))
    assert q.execute(con).fetchall() == [("carol",)]


def test_case(con: duckdb.DuckDBPyConnection) -> None:
    label = case().when(u.age < 30, "young").when(u.age < 40, "mid").else_("senior")
    q = select(u.name, label.as_("bucket")).from_(users).where(u.age.is_not_null()).order_by(u.id)
    assert q.execute(con).fetchall() == [("alice", "mid"), ("bob", "young"), ("carol", "senior"), ("eve", "mid")]

    simple = case(u.dept).when("eng", 1).else_(0)
    assert select(func.sum(simple)).from_(users).execute(con).fetchone() == (2,)


def test_cast(con: duckdb.DuckDBPyConnection) -> None:
    assert scalar(con, cast("42", qlt.Integer)) == 42
    assert scalar(con, val("x").try_cast("INTEGER")) is None
    assert scalar(con, cast("1.5", qlt.Decimal(4, 2))) == Decimal("1.50")
    with pytest.raises(ValueError, match="Invalid type name"):
        cast(1, "INTEGER); DROP TABLE users; --")


def test_functions(con: duckdb.DuckDBPyConnection) -> None:
    assert scalar(con, func.upper("abc")) == "ABC"
    assert scalar(con, func.coalesce(None, 3)) == 3
    q = select(func.string_agg(u.name, ",", order_by=u.name.desc())).from_(users).where(u.dept == "eng")
    assert q.execute(con).fetchone() == ("bob,alice",)
    assert select(func.count(u.dept, distinct=True)).from_(users).execute(con).fetchone() == (2,)


def test_aggregate_filter(con: duckdb.DuckDBPyConnection) -> None:
    q = select(func.count().filter(u.dept == "eng").as_("eng"), func.count().as_("all")).from_(users)
    assert q.sql == 'SELECT count(*) FILTER (WHERE ("users"."dept" = ?)) AS "eng", count(*) AS "all" FROM "users"'
    assert q.execute(con).fetchone() == (2, 5)


def test_window_function(con: duckdb.DuckDBPyConnection) -> None:
    rn = func.row_number().over(partition_by=u.dept, order_by=u.age.desc(nulls="last"))
    q = select(u.name, rn.as_("rn")).from_(users).where(u.dept.is_not_null()).order_by(u.dept, "rn")
    assert q.execute(con).fetchall() == [("alice", 1), ("bob", 2), ("carol", 1), ("dave", 2)]


def test_window_frame(con: duckdb.DuckDBPyConnection) -> None:
    o = table("orders").c
    running = func.sum(o.amount).over(order_by=o.ts, frame=rows_between(None, 0))
    assert (
        running.sql
        == 'sum("orders"."amount") OVER (ORDER BY "orders"."ts" ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)'
    )
    q = select(running).from_("orders").order_by(o.ts)
    assert [r[0] for r in q.execute(con).fetchall()] == [
        Decimal("100.00"),
        Decimal("150.50"),
        Decimal("170.50"),
        Decimal("1170.49"),
    ]


def test_named_window(con: duckdb.DuckDBPyConnection) -> None:
    q = (
        select(u.name, func.rank().over("w").as_("r"))
        .from_(users)
        .window("w", window(order_by=u.id))
        .order_by(u.id)
        .limit(2)
    )
    assert 'WINDOW "w" AS (ORDER BY "users"."id")' in q.sql
    assert q.execute(con).fetchall() == [("alice", 1), ("bob", 2)]


def test_index_and_struct(con: duckdb.DuckDBPyConnection) -> None:
    assert scalar(con, lit([10, 20, 30])[2]) == 20
    assert scalar(con, lit([10, 20, 30])[1:2]) == [10, 20]
    assert scalar(con, lit({"a": 1, "b": "x"})["b"]) == "x"


def test_star_exclude_replace(con: duckdb.DuckDBPyConnection) -> None:
    q = select(star(exclude=["age", "dept"], replace={"name": func.upper(u.name)})).from_(users).where(u.id == 1)
    assert q.sql.startswith('SELECT * EXCLUDE ("age", "dept") REPLACE (upper("users"."name") AS "name")')
    assert q.execute(con).fetchall() == [(1, "ALICE")]
    assert select(users.star(exclude=["age"])).from_(users).where(u.id == 2).execute(con).fetchone() == (
        2,
        "bob",
        "eng",
    )


def test_raw_sql_template(con: duckdb.DuckDBPyConnection) -> None:
    threshold = 30
    cond = sql(t"{u.age} > {threshold}")
    q = select(u.name).from_(users).where(cond).order_by(u.id)
    assert q.build().params == (30,)
    assert q.execute(con).fetchall() == [("carol",), ("eve",)]


def test_param_injection_is_safe(con: duckdb.DuckDBPyConnection) -> None:
    evil = "x'; DROP TABLE users; --"
    assert select(u.id).from_(users).where(u.name == evil).execute(con).fetchall() == []
    assert scalar(con, lit(evil)) == evil
    assert con.execute("SELECT count(*) FROM users").fetchone() == (5,)


def test_and_or_helpers() -> None:
    assert and_().sql == "true"
    assert or_().sql == "false"
    assert and_(col("a") == 1, col("b") == 2).sql == '(("a" = ?) AND ("b" = ?))'


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        42,
        1.5,
        Decimal("12.34"),
        "it's",
        b"\x00\xff",
        UUID("12345678-1234-5678-1234-567812345678"),
        datetime.date(2026, 11, 13),
        datetime.datetime(2026, 11, 13, 1, 2, 3),
        datetime.time(1, 2, 3),
        datetime.timedelta(days=1, seconds=5, microseconds=7),
        [1, 2, None],
        {"a": 1, "b": [True]},
    ],
)
def test_literal_round_trip(con: duckdb.DuckDBPyConnection, value: object) -> None:
    row = con.execute(f"SELECT {render_literal(value)}").fetchone()
    assert row is not None
    assert row[0] == value
