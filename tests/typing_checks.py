"""Static typing checks, verified by pyright and ty (not executed).

`assert_type` pins inferred types. Lines that must NOT type-check carry `# pyright: ignore[...]` and
`# ty: ignore[...]`; since the project reports unnecessary ignore comments as errors (pyright's
`reportUnnecessaryTypeIgnoreComment`, ty's `unused-ignore-comment`), both checkers fail if such a line ever starts
type-checking.
"""

import datetime
from typing import Any, assert_type

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

import parrotlet.functions as fn
import parrotlet.type as qlt
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
    assert_type(User.id, ColumnRef[qlt.BigInt])
    assert_type(User.tags, ColumnRef[qlt.List[qlt.Varchar]])
    assert_type(User.untyped, ColumnRef[Any])
    assert_type(col("x"), ColumnRef[Any])
    assert_type(col("x", type_=qlt.BigInt), ColumnRef[qlt.BigInt])


def operators() -> None:
    assert_type(User.id == 1, Expr[qlt.Boolean])
    assert_type(User.id < User.score, Expr[qlt.Boolean])  # numeric family
    assert_type(User.born < User.seen, Expr[qlt.Boolean])  # DATE vs TIMESTAMP
    assert_type(User.name == None, Expr[qlt.Boolean])  # noqa: E711
    assert_type(User.home == Point(0, 0), Expr[qlt.Boolean])
    assert_type((User.id > 1) & (User.name == "a"), Expr[qlt.Boolean])

    assert_type(User.id + 1, Expr[qlt.BigInt])
    assert_type(User.id + User.score, Expr[qlt.Double])
    assert_type(User.id + 1.5, Expr[qlt.Double])
    assert_type(User.id / 2, Expr[qlt.Double])
    assert_type(User.id // 2, Expr[qlt.BigInt])
    assert_type(User.born + 1, Expr[qlt.Date])
    assert_type(User.born + datetime.timedelta(hours=1), Expr[qlt.Timestamp])
    assert_type(User.seen - User.seen, Expr[qlt.Interval])
    assert_type(User.tags[1], Expr[qlt.Varchar])
    assert_type(User.tags[1:2], Expr[qlt.List[qlt.Varchar]])
    assert_type(User.name.concat("!"), Expr[qlt.Varchar])
    assert_type(User.id.cast(qlt.Varchar), Expr[qlt.Varchar])
    assert_type(cast("1", qlt.BigInt), Expr[qlt.BigInt])
    # types without arguments are classes, types with arguments are instances; both type the expression
    assert_type(User.id.cast(qlt.Integer()), Expr[qlt.Integer])
    assert_type(User.id.cast(qlt.Decimal(10, 2)), Expr[qlt.Decimal])
    assert_type(User.tags.cast(qlt.List(qlt.Varchar)), Expr[qlt.List[qlt.Varchar]])
    assert_type(col("m", type_=qlt.Map(qlt.Varchar, qlt.Integer)), ColumnRef[qlt.Map[qlt.Varchar, qlt.Integer]])
    assert_type(User.id.cast("INTEGER"), Expr[Any])
    User.id.cast(qlt.Integer(10))  # pyright: ignore[reportCallIssue]  # ty: ignore[too-many-positional-arguments]
    assert_type(val(1), Param[qlt.Integer])
    assert_type(lit("x"), Lit[qlt.Varchar])

    # untyped expressions stay usable everywhere
    assert_type(col("x") == "a", Expr[qlt.Boolean])
    assert_type(User.untyped + 1, Expr[Any])


def operator_errors() -> None:
    # `==` with an incompatible Python value falls back to `str.__eq__` (a plain bool), which no clause accepts:
    select(User.id).where(User.id == "1")  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    select(User.id).where(User.id == User.name)  # pyright: ignore[reportOperatorIssue]  # ty: ignore[invalid-argument-type]
    _ = User.name > 3  # pyright: ignore[reportOperatorIssue]  # ty: ignore[unsupported-operator]
    _ = User.id < User.name  # pyright: ignore[reportOperatorIssue]  # ty: ignore[unsupported-operator]
    _ = User.name + 1  # pyright: ignore[reportOperatorIssue]  # ty: ignore[unsupported-operator]
    _ = User.id & User.id  # pyright: ignore[reportOperatorIssue]  # ty: ignore[unsupported-operator]
    _ = ~User.name  # pyright: ignore[reportOperatorIssue]  # ty: ignore[unsupported-operator]
    _ = User.id.like("a%")  # pyright: ignore[reportAttributeAccessIssue]  # ty: ignore[invalid-argument-type]
    _ = User.born + User.born  # pyright: ignore[reportOperatorIssue]  # ty: ignore[unsupported-operator]


def statements() -> None:
    select(User.id).from_(User).where(User.id > 1).having(fn.count() > 1)
    select(User.id).from_(User).where(User.name)  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    select(User.id).from_(User).join(User, User.id)  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    # a window function without OVER is not an expression
    select(fn.row_number())  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    select(fn.row_number().over(order_by=User.id))


def functions() -> None:
    assert_type(fn.upper(User.name), Func[qlt.Varchar])
    assert_type(fn.length(User.name), Func[qlt.BigInt])
    assert_type(fn.date_trunc("day", User.born), Func[qlt.Timestamp])
    assert_type(fn.abs(User.id), Func[qlt.BigInt])
    assert_type(fn.sum(User.score), AggregateFunc[qlt.Double])
    assert_type(fn.count(), AggregateFunc[qlt.BigInt])
    assert_type(fn.max(User.seen), AggregateFunc[qlt.Timestamp])
    assert_type(fn.coalesce(User.id, 0), Func[qlt.BigInt])
    assert_type(fn.row_number(), WindowFunc[qlt.BigInt])
    assert_type(fn.lag(User.name), WindowFunc[qlt.Varchar])
    assert_type(fn.list_transform(User.tags, lambda s: fn.length(s)), Func[qlt.List[qlt.BigInt]])
    assert_type(fn.list_filter(User.tags, lambda s: s.like("a%")), Func[qlt.List[qlt.Varchar]])
    assert_type(fn.spatial.st_distance(User.home, Point(0, 0)), Func[qlt.Double])
    assert_type(fn.spatial.st_as_text(User.home), Func[qlt.Varchar])

    fn.upper(User.id)  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    fn.date_trunc("day", User.name)  # pyright: ignore[reportArgumentType, reportCallIssue]  # ty: ignore[no-matching-overload]
    fn.spatial.st_distance(User.home, User.name)  # pyright: ignore[reportArgumentType, reportCallIssue]  # ty: ignore[no-matching-overload]
    fn.list_filter(User.tags, lambda s: fn.length(s))  # pyright: ignore[reportArgumentType, reportCallIssue]  # ty: ignore[no-matching-overload]


def case_expressions() -> None:
    assert_type(case().when(User.id > 1, "big").when(User.id > 0, "mid").else_("small"), Case[qlt.Varchar])
    assert_type(case(User.id).when(1, User.score), SimpleCase[qlt.BigInt, qlt.Double])
    assert_type(fn.if_(User.id > 1, "a", "b"), Func[qlt.Varchar])
    case().when(User.name, "x")  # pyright: ignore[reportArgumentType, reportCallIssue]  # ty: ignore[no-matching-overload]


def duckdb_features() -> None:
    assert_type(list_comprehension(User.tags, lambda s: fn.length(s)), ListComprehension[qlt.List[qlt.BigInt]])
    assert_type(
        list_comprehension(User.tags, lambda s, i: i, where=lambda s, i: s.like("a%")),
        ListComprehension[qlt.List[qlt.BigInt]],
    )
    assert_type(any_(User.tags), Quantified[qlt.Varchar])
    assert_type(try_(User.id), Try[qlt.BigInt])
    assert_type(User.seen.at_time_zone("UTC"), Expr[qlt.TimestampTz])
    assert_type(User.tags.has_all(["a"]), Expr[qlt.Boolean])
    select(User.id).where(User.name == any_(User.tags))
    columns(lambda c: c.like("num%"))

    columns(lambda c: c + 1)  # pyright: ignore[reportOperatorIssue]  # ty: ignore[unsupported-operator]
    User.id.has_all([1])  # pyright: ignore[reportAttributeAccessIssue]  # ty: ignore[invalid-argument-type]
    User.tags.has_any(User.id)  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    User.name.at_time_zone("UTC")  # pyright: ignore[reportAttributeAccessIssue]  # ty: ignore[no-matching-overload]
    list_comprehension(User.name, lambda s: s)  # pyright: ignore[reportArgumentType, reportCallIssue]  # ty: ignore[no-matching-overload]


class Row(Model, table="rows"):
    id: Column[int] = column(primary_key=True)
    name: Column[str]
    note: Column[str | None] = column(default=None)
    created: Column[datetime.datetime] = column(default=fn.now())


def models_and_database(db: Database, other: User) -> None:
    r = Row(id=1, name="a")
    assert_type(r.id, int)
    assert_type(r.note, str | None)
    assert_type(Row.note, ColumnRef[qlt.Varchar])
    assert_type(table(Row), Table)
    assert_type(db.appender(Row), Appender[Row])
    assert_type(db.appender("rows"), Appender[Any])
    with db.appender(Row) as app:
        app.append(Row(id=1, name="a"))
        app.append(other)  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    assert_type(db.select(Row.id).from_(Row).where(Row.id > 1).fetch_as(Row), list[Row])
    assert_type(db.register(Row), type[Row])

    Row(id="1", name="a")  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
    Row(id=1)  # pyright: ignore[reportCallIssue]  # ty: ignore[missing-argument]
    r.name = 1  # pyright: ignore[reportAttributeAccessIssue]  # ty: ignore[invalid-assignment]
    db.select(Row.id).where(Row.name)  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
