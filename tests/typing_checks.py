"""Static typing checks, verified by pyright (not executed).

`assert_type` pins inferred types. Lines that must NOT type-check carry `# pyright: ignore[...]`; since the project
enables `reportUnnecessaryTypeIgnoreComment`, pyright fails if such a line ever starts type-checking.
"""

import datetime
from typing import Any, assert_type

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from parrotlet import (
    Appender,
    Column,
    Database,
    Model,
    Table,
    any_,
    case,
    cast,
    col,
    column,
    columns,
    list_comprehension,
    lit,
    select,
    table,
    try_,
    val,
)
from parrotlet import datatype as dt
from parrotlet import functions as F
from parrotlet import sqltypes as t
from parrotlet.expr import (
    AggregateFunc,
    Case,
    ColumnRef,
    Expr,
    Func,
    ListComprehension,
    Lit,
    Param,
    Quantified,
    SimpleCase,
    Try,
    WindowFunc,
)
from parrotlet.functions import spatial as ST


class User(Model, table="users"):
    id: Column[int] = column(primary_key=True)
    name: Column[str]
    score: Column[float]
    born: Column[datetime.date]
    seen: Column[datetime.datetime]
    tags: Column[list[str]]
    home: Column[BaseGeometry]
    untyped: Column[object] = column("INTEGER")


def column_types() -> None:
    assert_type(User.id, ColumnRef[t.BigInt])
    assert_type(User.tags, ColumnRef[t.List[t.Varchar]])
    assert_type(User.untyped, ColumnRef[Any])
    assert_type(col("x"), ColumnRef[Any])
    assert_type(col("x", type_=dt.BIGINT), ColumnRef[t.BigInt])


def operators() -> None:
    assert_type(User.id == 1, Expr[t.Boolean])
    assert_type(User.id < User.score, Expr[t.Boolean])  # numeric family
    assert_type(User.born < User.seen, Expr[t.Boolean])  # DATE vs TIMESTAMP
    assert_type(User.name == None, Expr[t.Boolean])  # noqa: E711
    assert_type(User.home == Point(0, 0), Expr[t.Boolean])
    assert_type((User.id > 1) & (User.name == "a"), Expr[t.Boolean])

    assert_type(User.id + 1, Expr[t.BigInt])
    assert_type(User.id + User.score, Expr[t.Double])
    assert_type(User.id + 1.5, Expr[t.Double])
    assert_type(User.id / 2, Expr[t.Double])
    assert_type(User.id // 2, Expr[t.BigInt])
    assert_type(User.born + 1, Expr[t.Date])
    assert_type(User.born + datetime.timedelta(hours=1), Expr[t.Timestamp])
    assert_type(User.seen - User.seen, Expr[t.Interval])
    assert_type(User.tags[1], Expr[t.Varchar])
    assert_type(User.tags[1:2], Expr[t.List[t.Varchar]])
    assert_type(User.name.concat("!"), Expr[t.Varchar])
    assert_type(User.id.cast(dt.VARCHAR), Expr[t.Varchar])
    assert_type(cast("1", dt.BIGINT), Expr[t.BigInt])
    assert_type(val(1), Param[t.Integer])
    assert_type(lit("x"), Lit[t.Varchar])

    # untyped expressions stay usable everywhere
    assert_type(col("x") == "a", Expr[t.Boolean])
    assert_type(User.untyped + 1, Expr[Any])


def operator_errors() -> None:
    # `==` with an incompatible Python value falls back to `str.__eq__` (a plain bool), which no clause accepts:
    select(User.id).where(User.id == "1")  # pyright: ignore[reportArgumentType]
    select(User.id).where(User.id == User.name)  # pyright: ignore[reportOperatorIssue]
    _ = User.name > 3  # pyright: ignore[reportOperatorIssue]
    _ = User.id < User.name  # pyright: ignore[reportOperatorIssue]
    _ = User.name + 1  # pyright: ignore[reportOperatorIssue]
    _ = User.id & User.id  # pyright: ignore[reportOperatorIssue]
    _ = ~User.name  # pyright: ignore[reportOperatorIssue]
    _ = User.id.like("a%")  # pyright: ignore[reportAttributeAccessIssue]
    _ = User.born + User.born  # pyright: ignore[reportOperatorIssue]


def statements() -> None:
    select(User.id).from_(User).where(User.id > 1).having(F.count() > 1)
    select(User.id).from_(User).where(User.name)  # pyright: ignore[reportArgumentType]
    select(User.id).from_(User).join(User, User.id)  # pyright: ignore[reportArgumentType]
    select(F.row_number())  # pyright: ignore[reportArgumentType]  (window function without OVER)
    select(F.row_number().over(order_by=User.id))


def functions() -> None:
    assert_type(F.upper(User.name), Func[t.Varchar])
    assert_type(F.length(User.name), Func[t.BigInt])
    assert_type(F.date_trunc("day", User.born), Func[t.Timestamp])
    assert_type(F.abs(User.id), Func[t.BigInt])
    assert_type(F.sum(User.score), AggregateFunc[t.Double])
    assert_type(F.count(), AggregateFunc[t.BigInt])
    assert_type(F.max(User.seen), AggregateFunc[t.Timestamp])
    assert_type(F.coalesce(User.id, 0), Func[t.BigInt])
    assert_type(F.row_number(), WindowFunc[t.BigInt])
    assert_type(F.lag(User.name), WindowFunc[t.Varchar])
    assert_type(F.list_transform(User.tags, lambda s: F.length(s)), Func[t.List[t.BigInt]])
    assert_type(F.list_filter(User.tags, lambda s: s.like("a%")), Func[t.List[t.Varchar]])
    assert_type(ST.st_distance(User.home, Point(0, 0)), Func[t.Double])
    assert_type(ST.st_as_text(User.home), Func[t.Varchar])

    F.upper(User.id)  # pyright: ignore[reportArgumentType]
    F.date_trunc("day", User.name)  # pyright: ignore[reportArgumentType, reportCallIssue]
    ST.st_distance(User.home, User.name)  # pyright: ignore[reportArgumentType, reportCallIssue]
    F.list_filter(User.tags, lambda s: F.length(s))  # pyright: ignore[reportArgumentType, reportCallIssue]


def case_expressions() -> None:
    assert_type(case().when(User.id > 1, "big").when(User.id > 0, "mid").else_("small"), Case[t.Varchar])
    assert_type(case(User.id).when(1, User.score), SimpleCase[t.BigInt, t.Double])
    assert_type(F.if_(User.id > 1, "a", "b"), Func[t.Varchar])
    case().when(User.name, "x")  # pyright: ignore[reportArgumentType, reportCallIssue]


def duckdb_features() -> None:
    assert_type(list_comprehension(User.tags, lambda s: F.length(s)), ListComprehension[t.List[t.BigInt]])
    assert_type(
        list_comprehension(User.tags, lambda s, i: i, where=lambda s, i: s.like("a%")),
        ListComprehension[t.List[t.BigInt]],
    )
    assert_type(any_(User.tags), Quantified[t.Varchar])
    assert_type(try_(User.id), Try[t.BigInt])
    assert_type(User.seen.at_time_zone("UTC"), Expr[t.TimestampTz])
    assert_type(User.tags.has_all(["a"]), Expr[t.Boolean])
    select(User.id).where(User.name == any_(User.tags))
    columns(lambda c: c.like("num%"))

    columns(lambda c: c + 1)  # pyright: ignore[reportOperatorIssue]
    User.id.has_all([1])  # pyright: ignore[reportAttributeAccessIssue]
    User.tags.has_any(User.id)  # pyright: ignore[reportArgumentType]
    User.name.at_time_zone("UTC")  # pyright: ignore[reportAttributeAccessIssue]
    list_comprehension(User.name, lambda s: s)  # pyright: ignore[reportArgumentType, reportCallIssue]


class Row(Model, table="rows"):
    id: Column[int] = column(primary_key=True)
    name: Column[str]
    note: Column[str | None] = column(default=None)
    created: Column[datetime.datetime] = column(default=F.now())


def models_and_database(db: Database, other: User) -> None:
    r = Row(id=1, name="a")
    assert_type(r.id, int)
    assert_type(r.note, str | None)
    assert_type(Row.note, ColumnRef[t.Varchar])
    assert_type(table(Row), Table)
    assert_type(db.appender(Row), Appender[Row])
    assert_type(db.appender("rows"), Appender[Any])
    with db.appender(Row) as app:
        app.append(Row(id=1, name="a"))
        app.append(other)  # pyright: ignore[reportArgumentType]
    assert_type(db.select(Row.id).from_(Row).where(Row.id > 1).fetch(Row), list[Row])
    assert_type(db.register(Row), type[Row])

    Row(id="1", name="a")  # pyright: ignore[reportArgumentType]
    Row(id=1)  # pyright: ignore[reportCallIssue]
    r.name = 1  # pyright: ignore[reportAttributeAccessIssue]
    db.select(Row.id).where(Row.name)  # pyright: ignore[reportArgumentType]
