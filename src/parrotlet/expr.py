"""Typed expressions: `Expr[T]` where `T` is a phantom SQL type from `parrotlet.sqltypes`.

Python operators build SQL and are type-checked by the operand types:

- comparison: `==` `!=` `<` `<=` `>` `>=` only between compatible types (`== None` becomes `IS NULL`)
- logical:    `&` (AND), `|` (OR), `~` (NOT) only on `Expr[Boolean]`
- arithmetic: `+` `-` `*` `/` `//` `%` `**` on numbers, plus date/time/interval arithmetic
- indexing:   `list_expr[1]`, `list_expr[1:3]`, `map_expr[key]`, `struct_expr["field"]`, `varchar_expr[1:3]`
"""

# pyright: reportOverlappingOverload=false

from __future__ import annotations

import datetime
import inspect
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal as PyDecimal
from string.templatelib import Template
from typing import Any, Literal, LiteralString, NoReturn, TypeVar, overload, override
from uuid import UUID

from shapely.geometry.base import BaseGeometry

from parrotlet import sqltypes as t
from parrotlet.datatype import DataType, to_type
from parrotlet.query import (
    EMPTY,
    Node,
    Query,
    RawSQL,
    concat,
    function_name,
    is_unqualified,
    join,
    param,
    qualified,
    quote_ident,
    render_literal,
    text,
)

type NullsOrder = Literal["first", "last"]
type FrameBound = int | datetime.timedelta | None
type PyNumber = int | float | PyDecimal
type PyScalar = (
    bool
    | int
    | float
    | PyDecimal
    | str
    | bytes
    | UUID
    | datetime.date
    | datetime.time
    | datetime.timedelta
    | BaseGeometry
    | list[Any]
    | dict[Any, Any]
    | None
)
"""Python values accepted where a SQL value is expected (bound as parameters)."""

type Bool = Expr[t.Boolean]

# Families of mutually comparable types. A constrained TypeVar resolves to exactly one family, so comparing e.g. an
# `Expr[Integer]` with an `Expr[Varchar]` is a type error while `Expr[Integer]` vs `Expr[Double]` is fine.
_Cmp = TypeVar(
    "_Cmp",
    t.Numeric,
    t.Varchar,
    t.Boolean,
    t.TimestampTz,
    t.TimeTz,
    t.Interval,
    t.Blob,
    t.Uuid,
    t.Bit,
    t.Geometry,
    t.List[Any],
    t.Map[Any, Any],
    t.Struct,
)
_N = TypeVar("_N", bound=t.Numeric)
_M = TypeVar("_M", bound=t.Numeric)
_TS = TypeVar("_TS", bound=t.TimestampTz)
_TM = TypeVar("_TM", bound=t.TimeTz)
_E = TypeVar("_E")
_K = TypeVar("_K")
_V = TypeVar("_V")
_U = TypeVar("_U")


# --------------------------------------------------------------------------------------------------------------------
# Coercion helpers (runtime)
# --------------------------------------------------------------------------------------------------------------------


def to_expr(value: object) -> Expr[Any]:
    """Coerce a value into an expression. Python values become bound parameters; statements become subqueries."""
    if isinstance(value, Expr):
        return value
    if isinstance(value, Node):
        return Subquery(value)
    return Param(value)


def to_column(value: object) -> Node:
    """Coerce an item in a column-list context: `str` is a column name, `"*"` is `*`, a Model class is `table.*`."""
    if isinstance(value, str):
        return Star() if value == "*" else ColumnRef(value)
    if isinstance(value, type) and hasattr(value, "__table__"):
        return Star(value.__table__.qualifier())
    if isinstance(value, Node):
        return value if isinstance(value, (Expr, Fragment)) else Subquery(value)
    return Param(value)


def to_column_expr(value: object) -> Expr[Any]:
    node = to_column(value)
    if not isinstance(node, Expr):
        raise TypeError(f"Expected an expression, got {type(node).__name__}")
    return node


def as_tuple[T](value: T | Sequence[T] | None) -> tuple[T, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)  # type: ignore[return-value]


class Fragment(Node):
    """A non-expression clause fragment (alias, ORDER BY item, ROLLUP ...) that column lists accept as-is."""

    __slots__ = ()


# --------------------------------------------------------------------------------------------------------------------
# Expression base
# --------------------------------------------------------------------------------------------------------------------


class Expr[T](Node):
    """Base class of every SQL expression; `T` is the phantom SQL type (see module docstring)."""

    __slots__ = ()
    __hash__ = object.__hash__

    def __bool__(self) -> bool:
        raise TypeError("SQL expressions have no truth value; use & | ~ instead of and/or/not")

    # comparison --------------------------------------------------------------------------------------------------
    @overload
    def __eq__(self, other: None) -> Bool: ...
    @overload
    def __eq__(self: Expr[_Cmp], other: Expr[_Cmp]) -> Bool: ...
    @overload
    def __eq__(self: Expr[t.Numeric], other: PyNumber) -> Bool: ...
    @overload
    def __eq__(self: Expr[t.Varchar], other: str) -> Bool: ...
    @overload
    def __eq__(self: Expr[t.Boolean], other: bool) -> Bool: ...
    @overload
    def __eq__(self: Expr[t.TimestampTz], other: datetime.date) -> Bool: ...
    @overload
    def __eq__(self: Expr[t.TimeTz], other: datetime.time) -> Bool: ...
    @overload
    def __eq__(self: Expr[t.Interval], other: datetime.timedelta) -> Bool: ...
    @overload
    def __eq__(self: Expr[t.Blob], other: bytes) -> Bool: ...
    @overload
    def __eq__(self: Expr[t.Uuid], other: UUID) -> Bool: ...
    @overload
    def __eq__(self: Expr[t.Geometry], other: BaseGeometry) -> Bool: ...
    @overload
    def __eq__(self: Expr[t.List[Any]], other: list[Any]) -> Bool: ...
    @overload
    def __eq__(self: Expr[t.Map[Any, Any]] | Expr[t.Struct], other: dict[Any, Any]) -> Bool: ...
    @override
    def __eq__(self, other: object) -> Bool:  # pyright: ignore[reportIncompatibleMethodOverride]
        if other is None:
            return self.is_null()
        return BinaryOp(self, "=", to_expr(other))

    @overload
    def __ne__(self, other: None) -> Bool: ...
    @overload
    def __ne__(self: Expr[_Cmp], other: Expr[_Cmp]) -> Bool: ...
    @overload
    def __ne__(self: Expr[t.Numeric], other: PyNumber) -> Bool: ...
    @overload
    def __ne__(self: Expr[t.Varchar], other: str) -> Bool: ...
    @overload
    def __ne__(self: Expr[t.Boolean], other: bool) -> Bool: ...
    @overload
    def __ne__(self: Expr[t.TimestampTz], other: datetime.date) -> Bool: ...
    @overload
    def __ne__(self: Expr[t.TimeTz], other: datetime.time) -> Bool: ...
    @overload
    def __ne__(self: Expr[t.Interval], other: datetime.timedelta) -> Bool: ...
    @overload
    def __ne__(self: Expr[t.Blob], other: bytes) -> Bool: ...
    @overload
    def __ne__(self: Expr[t.Uuid], other: UUID) -> Bool: ...
    @overload
    def __ne__(self: Expr[t.Geometry], other: BaseGeometry) -> Bool: ...
    @overload
    def __ne__(self: Expr[t.List[Any]], other: list[Any]) -> Bool: ...
    @overload
    def __ne__(self: Expr[t.Map[Any, Any]] | Expr[t.Struct], other: dict[Any, Any]) -> Bool: ...
    @override
    def __ne__(self, other: object) -> Bool:  # pyright: ignore[reportIncompatibleMethodOverride]
        if other is None:
            return self.is_not_null()
        return BinaryOp(self, "<>", to_expr(other))

    @overload
    def __lt__(self: Expr[_Cmp], other: Expr[_Cmp]) -> Bool: ...
    @overload
    def __lt__(self: Expr[t.Numeric], other: PyNumber) -> Bool: ...
    @overload
    def __lt__(self: Expr[t.Varchar], other: str) -> Bool: ...
    @overload
    def __lt__(self: Expr[t.TimestampTz], other: datetime.date) -> Bool: ...
    @overload
    def __lt__(self: Expr[t.TimeTz], other: datetime.time) -> Bool: ...
    @overload
    def __lt__(self: Expr[t.Interval], other: datetime.timedelta) -> Bool: ...
    def __lt__(self, other: object) -> Bool:
        return BinaryOp(self, "<", to_expr(other))

    @overload
    def __le__(self: Expr[_Cmp], other: Expr[_Cmp]) -> Bool: ...
    @overload
    def __le__(self: Expr[t.Numeric], other: PyNumber) -> Bool: ...
    @overload
    def __le__(self: Expr[t.Varchar], other: str) -> Bool: ...
    @overload
    def __le__(self: Expr[t.TimestampTz], other: datetime.date) -> Bool: ...
    @overload
    def __le__(self: Expr[t.TimeTz], other: datetime.time) -> Bool: ...
    @overload
    def __le__(self: Expr[t.Interval], other: datetime.timedelta) -> Bool: ...
    def __le__(self, other: object) -> Bool:
        return BinaryOp(self, "<=", to_expr(other))

    @overload
    def __gt__(self: Expr[_Cmp], other: Expr[_Cmp]) -> Bool: ...
    @overload
    def __gt__(self: Expr[t.Numeric], other: PyNumber) -> Bool: ...
    @overload
    def __gt__(self: Expr[t.Varchar], other: str) -> Bool: ...
    @overload
    def __gt__(self: Expr[t.TimestampTz], other: datetime.date) -> Bool: ...
    @overload
    def __gt__(self: Expr[t.TimeTz], other: datetime.time) -> Bool: ...
    @overload
    def __gt__(self: Expr[t.Interval], other: datetime.timedelta) -> Bool: ...
    def __gt__(self, other: object) -> Bool:
        return BinaryOp(self, ">", to_expr(other))

    @overload
    def __ge__(self: Expr[_Cmp], other: Expr[_Cmp]) -> Bool: ...
    @overload
    def __ge__(self: Expr[t.Numeric], other: PyNumber) -> Bool: ...
    @overload
    def __ge__(self: Expr[t.Varchar], other: str) -> Bool: ...
    @overload
    def __ge__(self: Expr[t.TimestampTz], other: datetime.date) -> Bool: ...
    @overload
    def __ge__(self: Expr[t.TimeTz], other: datetime.time) -> Bool: ...
    @overload
    def __ge__(self: Expr[t.Interval], other: datetime.timedelta) -> Bool: ...
    def __ge__(self, other: object) -> Bool:
        return BinaryOp(self, ">=", to_expr(other))

    # logical -----------------------------------------------------------------------------------------------------
    def __and__(self: Expr[t.Boolean], other: Expr[t.Boolean] | bool) -> Bool:
        return BinaryOp(self, "AND", to_expr(other))

    def __rand__(self: Expr[t.Boolean], other: bool) -> Bool:
        return BinaryOp(to_expr(other), "AND", self)

    def __or__(self: Expr[t.Boolean], other: Expr[t.Boolean] | bool) -> Bool:
        return BinaryOp(self, "OR", to_expr(other))

    def __ror__(self: Expr[t.Boolean], other: bool) -> Bool:
        return BinaryOp(to_expr(other), "OR", self)

    def __invert__(self: Expr[t.Boolean]) -> Bool:
        return UnaryOp("NOT ", self)

    # arithmetic --------------------------------------------------------------------------------------------------
    @overload
    def __add__(self: Expr[_N], other: Expr[_N] | int | PyDecimal) -> Expr[_N]: ...
    @overload
    def __add__(self: Expr[_N], other: Expr[_M]) -> Expr[_M]: ...
    @overload
    def __add__(self: Expr[t.Numeric], other: float) -> Expr[t.Double]: ...
    @overload
    def __add__(self: Expr[t.Date], other: Expr[t.Integer] | int) -> Expr[t.Date]: ...
    @overload
    def __add__(self: Expr[t.Date], other: Expr[t.Interval] | datetime.timedelta) -> Expr[t.Timestamp]: ...
    @overload
    def __add__(self: Expr[_TS], other: Expr[t.Interval] | datetime.timedelta) -> Expr[_TS]: ...
    @overload
    def __add__(self: Expr[_TM], other: Expr[t.Interval] | datetime.timedelta) -> Expr[_TM]: ...
    @overload
    def __add__(self: Expr[t.Interval], other: Expr[t.Interval] | datetime.timedelta) -> Expr[t.Interval]: ...
    def __add__(self, other: object) -> Expr[Any]:
        return BinaryOp(self, "+", to_expr(other))

    @overload
    def __radd__(self: Expr[_N], other: int | PyDecimal) -> Expr[_N]: ...
    @overload
    def __radd__(self: Expr[t.Numeric], other: float) -> Expr[t.Double]: ...
    def __radd__(self, other: object) -> Expr[Any]:
        return BinaryOp(to_expr(other), "+", self)

    @overload
    def __sub__(self: Expr[_N], other: Expr[_N] | int | PyDecimal) -> Expr[_N]: ...
    @overload
    def __sub__(self: Expr[_N], other: Expr[_M]) -> Expr[_M]: ...
    @overload
    def __sub__(self: Expr[t.Numeric], other: float) -> Expr[t.Double]: ...
    @overload
    def __sub__(self: Expr[t.Date], other: Expr[t.Integer] | int) -> Expr[t.Date]: ...
    @overload
    def __sub__(self: Expr[t.Date], other: Expr[t.Date]) -> Expr[t.BigInt]: ...
    @overload
    def __sub__(self: Expr[t.Date], other: Expr[t.Interval] | datetime.timedelta) -> Expr[t.Timestamp]: ...
    @overload
    def __sub__(self: Expr[_TS], other: Expr[t.Interval] | datetime.timedelta) -> Expr[_TS]: ...
    @overload
    def __sub__(self: Expr[t.TimestampTz], other: Expr[t.TimestampTz] | datetime.datetime) -> Expr[t.Interval]: ...
    @overload
    def __sub__(self: Expr[_TM], other: Expr[t.Interval] | datetime.timedelta) -> Expr[_TM]: ...
    @overload
    def __sub__(self: Expr[t.Interval], other: Expr[t.Interval] | datetime.timedelta) -> Expr[t.Interval]: ...
    def __sub__(self, other: object) -> Expr[Any]:
        return BinaryOp(self, "-", to_expr(other))

    @overload
    def __rsub__(self: Expr[_N], other: int | PyDecimal) -> Expr[_N]: ...
    @overload
    def __rsub__(self: Expr[t.Numeric], other: float) -> Expr[t.Double]: ...
    def __rsub__(self, other: object) -> Expr[Any]:
        return BinaryOp(to_expr(other), "-", self)

    @overload
    def __mul__(self: Expr[_N], other: Expr[_N] | int | PyDecimal) -> Expr[_N]: ...
    @overload
    def __mul__(self: Expr[_N], other: Expr[_M]) -> Expr[_M]: ...
    @overload
    def __mul__(self: Expr[t.Numeric], other: float) -> Expr[t.Double]: ...
    @overload
    def __mul__(self: Expr[t.Interval], other: Expr[t.Numeric] | PyNumber) -> Expr[t.Interval]: ...
    def __mul__(self, other: object) -> Expr[Any]:
        return BinaryOp(self, "*", to_expr(other))

    @overload
    def __rmul__(self: Expr[_N], other: int | PyDecimal) -> Expr[_N]: ...
    @overload
    def __rmul__(self: Expr[t.Numeric], other: float) -> Expr[t.Double]: ...
    @overload
    def __rmul__(self: Expr[t.Interval], other: PyNumber) -> Expr[t.Interval]: ...
    def __rmul__(self, other: object) -> Expr[Any]:
        return BinaryOp(to_expr(other), "*", self)

    @overload
    def __truediv__(self: Expr[t.Numeric], other: Expr[t.Numeric] | PyNumber) -> Expr[t.Double]: ...
    @overload
    def __truediv__(self: Expr[t.Interval], other: Expr[t.Numeric] | PyNumber) -> Expr[t.Interval]: ...
    def __truediv__(self, other: object) -> Expr[Any]:
        """`/` is floating-point division in DuckDB (use `//` for integer division)."""
        return BinaryOp(self, "/", to_expr(other))

    def __rtruediv__(self: Expr[t.Numeric], other: PyNumber) -> Expr[t.Double]:
        return BinaryOp(to_expr(other), "/", self)

    @overload
    def __floordiv__(self: Expr[_N], other: Expr[_N] | int) -> Expr[_N]: ...
    @overload
    def __floordiv__(self: Expr[_N], other: Expr[_M]) -> Expr[_M]: ...
    def __floordiv__(self, other: object) -> Expr[Any]:
        return BinaryOp(self, "//", to_expr(other))

    def __rfloordiv__(self: Expr[_N], other: int) -> Expr[_N]:
        return BinaryOp(to_expr(other), "//", self)

    @overload
    def __mod__(self: Expr[_N], other: Expr[_N] | int | PyDecimal) -> Expr[_N]: ...
    @overload
    def __mod__(self: Expr[_N], other: Expr[_M]) -> Expr[_M]: ...
    @overload
    def __mod__(self: Expr[t.Numeric], other: float) -> Expr[t.Double]: ...
    def __mod__(self, other: object) -> Expr[Any]:
        return BinaryOp(self, "%", to_expr(other))

    def __rmod__(self: Expr[_N], other: int) -> Expr[_N]:
        return BinaryOp(to_expr(other), "%", self)

    def __pow__(self: Expr[t.Numeric], other: Expr[t.Numeric] | PyNumber) -> Expr[t.Double]:
        return BinaryOp(self, "**", to_expr(other))

    def __rpow__(self: Expr[t.Numeric], other: PyNumber) -> Expr[t.Double]:
        return BinaryOp(to_expr(other), "**", self)

    @overload
    def __neg__(self: Expr[_N]) -> Expr[_N]: ...
    @overload
    def __neg__(self: Expr[t.Interval]) -> Expr[t.Interval]: ...
    def __neg__(self) -> Expr[Any]:
        return UnaryOp("-", self)

    # indexing ----------------------------------------------------------------------------------------------------
    @overload
    def __getitem__(self: Expr[t.List[_E]], key: int | Expr[t.BigInt]) -> Expr[_E]: ...
    @overload
    def __getitem__(self: Expr[t.List[_E]], key: slice) -> Expr[t.List[_E]]: ...
    @overload
    def __getitem__(self: Expr[t.Varchar], key: int | slice) -> Expr[t.Varchar]: ...
    @overload
    def __getitem__(self: Expr[t.Map[_K, _V]], key: object) -> Expr[_V]: ...
    @overload
    def __getitem__(self: Expr[t.Struct], key: str) -> Expr[Any]: ...
    def __getitem__(self, key: object) -> Expr[Any]:
        return Index(self, key)

    # named operators ---------------------------------------------------------------------------------------------
    @overload
    def concat(self: Expr[t.Varchar], other: Expr[t.Varchar] | str) -> Expr[t.Varchar]: ...
    @overload
    def concat(self: Expr[t.List[_E]], other: Expr[t.List[_E]]) -> Expr[t.List[_E]]: ...
    @overload
    def concat(self: Expr[t.Blob], other: Expr[t.Blob] | bytes) -> Expr[t.Blob]: ...
    def concat(self, other: object) -> Expr[Any]:
        """`self || other`"""
        return BinaryOp(self, "||", to_expr(other))

    def is_null(self) -> Bool:
        return PostfixOp(self, " IS NULL")

    def is_not_null(self) -> Bool:
        return PostfixOp(self, " IS NOT NULL")

    def is_distinct_from(self: Expr[_Cmp], other: Expr[_Cmp] | PyScalar) -> Bool:
        return BinaryOp(self, "IS DISTINCT FROM", to_expr(other))

    def is_not_distinct_from(self: Expr[_Cmp], other: Expr[_Cmp] | PyScalar) -> Bool:
        return BinaryOp(self, "IS NOT DISTINCT FROM", to_expr(other))

    def in_(self: Expr[_Cmp], values: Iterable[Expr[_Cmp] | PyScalar] | Node) -> Bool:
        """`IN (v1, v2, ...)` or `IN (subquery)`."""
        return _in(self, values, negate=False)

    def not_in(self: Expr[_Cmp], values: Iterable[Expr[_Cmp] | PyScalar] | Node) -> Bool:
        return _in(self, values, negate=True)

    def between(self: Expr[_Cmp], low: Expr[_Cmp] | PyScalar, high: Expr[_Cmp] | PyScalar) -> Bool:
        return Between(self, to_expr(low), to_expr(high), negate=False)

    def not_between(self: Expr[_Cmp], low: Expr[_Cmp] | PyScalar, high: Expr[_Cmp] | PyScalar) -> Bool:
        return Between(self, to_expr(low), to_expr(high), negate=True)

    def like(self: Expr[t.Varchar], pattern: Expr[t.Varchar] | str, escape: str | None = None) -> Bool:
        return Like(self, "LIKE", to_expr(pattern), escape)

    def not_like(self: Expr[t.Varchar], pattern: Expr[t.Varchar] | str, escape: str | None = None) -> Bool:
        return Like(self, "NOT LIKE", to_expr(pattern), escape)

    def ilike(self: Expr[t.Varchar], pattern: Expr[t.Varchar] | str, escape: str | None = None) -> Bool:
        return Like(self, "ILIKE", to_expr(pattern), escape)

    def not_ilike(self: Expr[t.Varchar], pattern: Expr[t.Varchar] | str, escape: str | None = None) -> Bool:
        return Like(self, "NOT ILIKE", to_expr(pattern), escape)

    def glob(self: Expr[t.Varchar], pattern: Expr[t.Varchar] | str) -> Bool:
        return BinaryOp(self, "GLOB", to_expr(pattern))

    def similar_to(self: Expr[t.Varchar], pattern: Expr[t.Varchar] | str) -> Bool:
        return BinaryOp(self, "SIMILAR TO", to_expr(pattern))

    @overload
    def cast(self, type_: DataType[_U]) -> Expr[_U]: ...
    @overload
    def cast(self, type_: str) -> Expr[Any]: ...
    def cast(self, type_: DataType[Any] | str) -> Expr[Any]:
        return Cast(self, to_type(type_), try_=False)

    @overload
    def try_cast(self, type_: DataType[_U]) -> Expr[_U]: ...
    @overload
    def try_cast(self, type_: str) -> Expr[Any]: ...
    def try_cast(self, type_: DataType[Any] | str) -> Expr[Any]:
        return Cast(self, to_type(type_), try_=True)

    def collate(self: Expr[t.Varchar], collation: str) -> Expr[t.Varchar]:
        return PostfixOp(self, f" COLLATE {quote_ident(collation)}")

    # boolean tests -----------------------------------------------------------------------------------------------
    def is_true(self: Expr[t.Boolean]) -> Bool:
        return PostfixOp(self, " IS TRUE")

    def is_false(self: Expr[t.Boolean]) -> Bool:
        return PostfixOp(self, " IS FALSE")

    def is_not_true(self: Expr[t.Boolean]) -> Bool:
        return PostfixOp(self, " IS NOT TRUE")

    def is_not_false(self: Expr[t.Boolean]) -> Bool:
        return PostfixOp(self, " IS NOT FALSE")

    # DuckDB operators --------------------------------------------------------------------------------------------
    def json_get(self: Expr[t.Varchar], path: Expr[t.Varchar] | Expr[t.BigInt] | str | int) -> Expr[t.Json]:
        """`json -> path` (JSON path such as `'$.a.b'`, a key, or an array index)."""
        return BinaryOp(self, "->", to_expr(path))

    def json_get_text(self: Expr[t.Varchar], path: Expr[t.Varchar] | Expr[t.BigInt] | str | int) -> Expr[t.Varchar]:
        """`json ->> path` (the value as VARCHAR)."""
        return BinaryOp(self, "->>", to_expr(path))

    def has_all(self: Expr[t.List[_E]], other: Expr[t.List[_E]] | list[Any]) -> Bool:
        """`list @> other`: the list contains every element of `other`."""
        return BinaryOp(self, "@>", to_expr(other))

    def contained_by(self: Expr[t.List[_E]], other: Expr[t.List[_E]] | list[Any]) -> Bool:
        """`list <@ other`: every element is in `other`."""
        return BinaryOp(self, "<@", to_expr(other))

    def has_any(self: Expr[t.List[_E]], other: Expr[t.List[_E]] | list[Any]) -> Bool:
        """`list && other`: the lists share an element."""
        return BinaryOp(self, "&&", to_expr(other))

    @overload
    def at_time_zone(self: Expr[t.Timestamp], zone: Expr[t.Varchar] | str) -> Expr[t.TimestampTz]: ...
    @overload
    def at_time_zone(self: Expr[t.TimestampTz], zone: Expr[t.Varchar] | str) -> Expr[t.Timestamp]: ...
    def at_time_zone(self, zone: Expr[t.Varchar] | str) -> Expr[Any]:
        """`ts AT TIME ZONE zone`: TIMESTAMP -> TIMESTAMPTZ (interpreted in `zone`), TIMESTAMPTZ -> local TIMESTAMP."""
        return BinaryOp(self, "AT TIME ZONE", to_expr(zone))

    def __iter__(self) -> NoReturn:
        # Expr defines __getitem__, which would otherwise make every expression silently "iterable".
        raise TypeError(f"{type(self).__name__} is not iterable (only columns(...) can be unpacked with *)")

    # aliasing / ordering -----------------------------------------------------------------------------------------
    def as_(self, alias: str) -> Aliased:
        return Aliased(self, alias)

    def asc(self, nulls: NullsOrder | None = None) -> OrderItem:
        return OrderItem(self, desc=False, nulls=nulls)

    def desc(self, nulls: NullsOrder | None = None) -> OrderItem:
        return OrderItem(self, desc=True, nulls=nulls)


def _in(expr: Expr[Any], values: Iterable[object] | Node, *, negate: bool) -> Bool:
    if isinstance(values, Node) and not isinstance(values, Expr):
        return InSubquery(expr, values, negate=negate)
    if isinstance(values, (str, bytes)):
        raise TypeError("in_() expects an iterable of values, not a string")
    if isinstance(values, Expr):
        raise TypeError("in_() expects an iterable of values or a subquery; for list columns use list_contains")
    items = tuple(to_expr(v) for v in values)
    if not items:
        return Lit(negate)  # x IN () is always false, x NOT IN () always true
    return InList(expr, items, negate=negate)


# --------------------------------------------------------------------------------------------------------------------
# Leaf expressions
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class ColumnRef[T](Expr[T]):
    name: str
    qualifier: tuple[str, ...] = ()

    @override
    def build(self) -> Query:
        if is_unqualified():
            return Query(quote_ident(self.name))
        return Query(qualified(*self.qualifier, self.name))

    def star(self: ColumnRef[t.Struct]) -> Star:
        """`col.*`: expand a STRUCT column into one column per field."""
        return Star((*self.qualifier, self.name))


@dataclass(frozen=True, slots=True, eq=False)
class PositionalRef(Expr[Any]):
    """`#n`: the n-th column of the FROM clause (1-based)."""

    position: int

    @override
    def build(self) -> Query:
        return Query(f"#{int(self.position)}")


@dataclass(frozen=True, slots=True, eq=False)
class Param[T](Expr[T]):
    """A bound `?` parameter."""

    value: object

    @override
    def build(self) -> Query:
        return param(self.value)


@dataclass(frozen=True, slots=True, eq=False)
class Lit[T](Expr[T]):
    """A value rendered inline as a SQL literal (not a parameter)."""

    value: object

    @override
    def build(self) -> Query:
        return Query(render_literal(self.value))


@dataclass(frozen=True, slots=True, eq=False)
class Keyword[T](Expr[T]):
    """A trusted bare keyword such as `DEFAULT`, `CURRENT_DATE`."""

    keyword: str

    @override
    def build(self) -> Query:
        return Query(self.keyword)


@dataclass(frozen=True, slots=True, eq=False)
class SQL[T](Expr[T]):
    """Raw SQL from a t-string. Interpolated values become parameters; nodes are embedded."""

    template: Template

    @override
    def build(self) -> Query:
        return concat("(", RawSQL(self.template), ")")


type StarPattern = Literal["LIKE", "NOT LIKE", "ILIKE", "NOT ILIKE", "GLOB", "SIMILAR TO"]


@dataclass(frozen=True, slots=True, eq=False)
class Star(Expr[Any]):
    """`*` / `t.*` / `struct_col.*` with DuckDB's modifiers, rendered in the order DuckDB requires:

    `* EXCLUDE (...) [LIKE|ILIKE|GLOB|SIMILAR TO 'pattern'] REPLACE (...) RENAME (...)`
    """

    qualifier: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    replace: tuple[tuple[Expr[Any], str], ...] = ()
    rename: tuple[tuple[str, str], ...] = ()
    pattern: tuple[StarPattern, str] | None = None

    def __post_init__(self) -> None:
        if self.pattern is not None and self.rename:
            raise ValueError("DuckDB cannot combine a star pattern (LIKE/GLOB/...) with RENAME")

    @override
    def build(self) -> Query:
        # DuckDB accepts a single name before `.*` (a table, alias or struct column), so drop schema/catalog parts.
        q = Query((qualified(self.qualifier[-1]) + ".*") if self.qualifier else "*")
        if self.exclude:
            q += Query(" EXCLUDE (" + ", ".join(quote_ident(c) for c in self.exclude) + ")")
        if self.pattern is not None:
            op, pattern = self.pattern
            q += Query(f" {op} {render_literal(pattern)}")  # must be a constant, so never a parameter
        if self.replace:
            q += concat(
                " REPLACE (",
                join(", ", (concat(e, " AS ", Query(quote_ident(n))) for e, n in self.replace)),
                ")",
            )
        if self.rename:
            q += Query(" RENAME (" + ", ".join(f"{quote_ident(a)} AS {quote_ident(b)}" for a, b in self.rename) + ")")
        return q


@dataclass(frozen=True, slots=True, eq=False)
class ColumnsExpr(Expr[Any]):
    """DuckDB `COLUMNS(...)`: a regex, a list of names, a lambda over column names, or a star expression.

    Use it like a column (`F.max(columns("num_.*"))` applies to every matching column), alias it with regex capture
    groups (`columns("num_(.*)").as_(r"x_\\1")`), or unpack it into a function call with `*`:
    `F.coalesce(*columns("num_.*"))` renders `coalesce(*COLUMNS('num_.*'))`.
    """

    selector: Node

    @override
    def build(self) -> Query:
        return concat("COLUMNS(", self.selector, ")")

    @override
    def __iter__(self) -> Iterator[Expr[Any]]:  # pyright: ignore[reportIncompatibleMethodOverride]
        yield Unpacked(self)


@dataclass(frozen=True, slots=True, eq=False)
class Unpacked(Expr[Any]):
    """`*COLUMNS(...)`: the matched columns as separate function arguments."""

    columns: ColumnsExpr

    @override
    def build(self) -> Query:
        return concat("*", self.columns)


# --------------------------------------------------------------------------------------------------------------------
# Operators
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class BinaryOp[T](Expr[T]):
    left: Expr[Any]
    op: str
    right: Expr[Any]

    @override
    def build(self) -> Query:
        return concat("(", self.left, Query(f" {self.op} "), self.right, ")")


@dataclass(frozen=True, slots=True, eq=False)
class UnaryOp[T](Expr[T]):
    op: str
    operand: Expr[Any]

    @override
    def build(self) -> Query:
        return concat("(", Query(self.op), self.operand, ")")


@dataclass(frozen=True, slots=True, eq=False)
class PostfixOp[T](Expr[T]):
    operand: Expr[Any]
    op: str

    @override
    def build(self) -> Query:
        return concat("(", self.operand, Query(self.op), ")")


@dataclass(frozen=True, slots=True, eq=False)
class InList(Expr[t.Boolean]):
    expr: Expr[Any]
    items: tuple[Expr[Any], ...]
    negate: bool

    @override
    def build(self) -> Query:
        return concat("(", self.expr, " NOT IN (" if self.negate else " IN (", join(", ", self.items), "))")


@dataclass(frozen=True, slots=True, eq=False)
class InSubquery(Expr[t.Boolean]):
    expr: Expr[Any]
    query: Node
    negate: bool

    @override
    def build(self) -> Query:
        return concat("(", self.expr, " NOT IN (" if self.negate else " IN (", self.query, "))")


@dataclass(frozen=True, slots=True, eq=False)
class Between(Expr[t.Boolean]):
    expr: Expr[Any]
    low: Expr[Any]
    high: Expr[Any]
    negate: bool

    @override
    def build(self) -> Query:
        kw = " NOT BETWEEN " if self.negate else " BETWEEN "
        return concat("(", self.expr, kw, self.low, " AND ", self.high, ")")


@dataclass(frozen=True, slots=True, eq=False)
class Like(Expr[t.Boolean]):
    expr: Expr[Any]
    op: str
    pattern: Expr[Any]
    escape: str | None

    @override
    def build(self) -> Query:
        esc = Query(f" ESCAPE {render_literal(self.escape)}") if self.escape is not None else None
        return concat("(", self.expr, Query(f" {self.op} "), self.pattern, esc, ")")


@dataclass(frozen=True, slots=True, eq=False)
class Index[T](Expr[T]):
    expr: Expr[Any]
    key: object

    @override
    def build(self) -> Query:
        key = self.key
        if isinstance(key, slice):
            lo = _index_part(key.start) if key.start is not None else EMPTY
            hi = _index_part(key.stop) if key.stop is not None else EMPTY
            step = concat(":", _index_part(key.step)) if key.step is not None else None
            return concat("(", self.expr, ")[", lo, ":", hi, step, "]")
        return concat("(", self.expr, ")[", _index_part(key), "]")


def _index_part(value: object) -> Query:
    # struct keys and integer indices must be constants at bind time, so render them inline
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        return Query(render_literal(value))
    return to_expr(value).build()


@dataclass(frozen=True, slots=True, eq=False)
class Cast[T](Expr[T]):
    expr: Expr[Any]
    type_: DataType[Any]
    try_: bool

    @override
    def build(self) -> Query:
        return concat("TRY_CAST(" if self.try_ else "CAST(", self.expr, " AS ", self.type_, ")")


@dataclass(frozen=True, slots=True, eq=False)
class Subquery[T](Expr[T]):
    """A statement used as a scalar expression: `(SELECT ...)`."""

    query: Node

    @override
    def build(self) -> Query:
        return concat("(", self.query, ")")


@dataclass(frozen=True, slots=True, eq=False)
class Exists(Expr[t.Boolean]):
    query: Node
    negate: bool = False

    @override
    def build(self) -> Query:
        return concat("(NOT EXISTS (" if self.negate else "(EXISTS (", self.query, "))")


@dataclass(frozen=True, slots=True, eq=False)
class Lambda(Expr[Any]):
    """DuckDB lambda `lambda x, y: body`, built from a Python callable by `make_lambda`."""

    names: tuple[str, ...]
    body: Expr[Any]

    @override
    def build(self) -> Query:
        return concat(Query("lambda " + ", ".join(quote_ident(p) for p in self.names) + ": "), self.body)


def cast_callable(fn: object) -> Callable[..., Expr[Any]]:
    return fn  # type: ignore[return-value]


def make_lambda(fn: Callable[..., Expr[Any]]) -> Lambda:
    """Turn `lambda x: x + 1` into a SQL lambda; the Python parameters become SQL lambda parameters."""
    names = tuple(inspect.signature(fn).parameters)
    if not names:
        raise ValueError("A SQL lambda needs at least one parameter")
    return Lambda(names, to_expr(fn(*(ColumnRef[Any](n) for n in names))))


@dataclass(frozen=True, slots=True, eq=False)
class ListComprehension[T](Expr[T]):
    """`[expr FOR x[, i] IN values IF condition]`"""

    values: Expr[Any]
    names: tuple[str, ...]
    body: Expr[Any]
    condition: Expr[Any] | None = None

    @override
    def build(self) -> Query:
        return concat(
            "[",
            self.body,
            Query(" FOR " + ", ".join(quote_ident(n) for n in self.names) + " IN "),
            self.values,
            concat(" IF ", self.condition) if self.condition is not None else None,
            "]",
        )


@dataclass(frozen=True, slots=True, eq=False)
class Quantified[T](Expr[T]):
    """`ANY (subquery)` / `ALL (subquery)` / `ANY(list)` on the right-hand side of a comparison."""

    quantifier: Literal["ANY", "ALL"]
    source: Node

    @override
    def build(self) -> Query:
        return concat(Query(self.quantifier + " ("), self.source, ")")


@dataclass(frozen=True, slots=True, eq=False)
class Try[T](Expr[T]):
    """`TRY(expr)`: NULL instead of an error."""

    expr: Expr[Any]

    @override
    def build(self) -> Query:
        return concat("TRY(", self.expr, ")")


# --------------------------------------------------------------------------------------------------------------------
# Function calls
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Func[T](Expr[T]):
    """A scalar function call."""

    name: str
    args: tuple[Node, ...] = ()
    named: tuple[tuple[str, Expr[Any]], ...] = ()
    extension: str | None = None
    """The DuckDB extension providing the function; it is installed/loaded automatically before execution."""

    def _args(self) -> Query:
        named = (concat(Query(quote_ident(k) + " := "), v) for k, v in self.named)
        return join(", ", (*self.args, *named))

    def _head(self) -> Query:
        return Query(function_name(self.name) + "(", extensions=frozenset({self.extension} if self.extension else ()))

    @override
    def build(self) -> Query:
        return concat(self._head(), self._args(), ")")


@dataclass(frozen=True, slots=True, eq=False)
class AggregateFunc[T](Func[T]):
    """An aggregate function call: supports DISTINCT, ORDER BY (ordered aggregates), FILTER and OVER."""

    distinct: bool = False
    order_by: tuple[Node, ...] = ()
    filter_: Expr[t.Boolean] | None = None

    @override
    def build(self) -> Query:
        q = concat(
            self._head(),
            "DISTINCT " if self.distinct else None,
            self._args(),
            concat(" ORDER BY ", join(", ", self.order_by)) if self.order_by else None,
            ")",
        )
        if self.filter_ is not None:
            q += concat(" FILTER (WHERE ", self.filter_, ")")
        return q

    def filter(self, condition: Expr[t.Boolean]) -> AggregateFunc[T]:
        """`FILTER (WHERE condition)`."""
        cond = condition if self.filter_ is None else (self.filter_ & condition)
        return AggregateFunc(
            self.name,
            self.args,
            self.named,
            self.extension,
            distinct=self.distinct,
            order_by=self.order_by,
            filter_=cond,
        )

    def over(
        self,
        window: str | Window | None = None,
        *,
        partition_by: object | Sequence[object] | None = None,
        order_by: object | Sequence[object] | None = None,
        frame: Frame | None = None,
    ) -> Expr[T]:
        """Use the aggregate as a window function: `sum(x).over(partition_by=...)`."""
        return Over(self, _window_spec(window, partition_by, order_by, frame))


@dataclass(frozen=True, slots=True, eq=False)
class WindowFunc[T](Node):
    """A window-only function (`row_number()`, `lag(x)`, ...). It is not an expression until `.over(...)` is applied."""

    name: str
    args: tuple[Node, ...] = ()
    ignore_nulls: bool = False
    order_by: tuple[Node, ...] = ()
    extension: str | None = None

    @override
    def build(self) -> Query:
        return concat(
            Query(function_name(self.name) + "(", extensions=frozenset({self.extension} if self.extension else ())),
            join(", ", self.args),
            concat(" ORDER BY ", join(", ", self.order_by)) if self.order_by else None,
            " IGNORE NULLS" if self.ignore_nulls else None,
            ")",
        )

    def over(
        self,
        window: str | Window | None = None,
        *,
        partition_by: object | Sequence[object] | None = None,
        order_by: object | Sequence[object] | None = None,
        frame: Frame | None = None,
    ) -> Expr[T]:
        return Over(self, _window_spec(window, partition_by, order_by, frame))


def _window_spec(
    window: str | Window | None,
    partition_by: object | Sequence[object] | None,
    order_by: object | Sequence[object] | None,
    frame: Frame | None,
) -> Window:
    if isinstance(window, Window):
        return window
    return Window(
        base=window,
        partition_by=tuple(to_column_expr(e) for e in as_tuple(partition_by)),
        order_by=tuple(to_column(e) for e in as_tuple(order_by)),
        frame=frame,
    )


class _FuncNamespace:
    """Untyped escape hatch: `func.<name>(*args)` calls any function and returns `AggregateFunc[Any]`.

    Prefer the typed functions in `parrotlet.functions` / `parrotlet.functions.spatial`.
    """

    def __call__(
        self,
        name: str,
        *args: object,
        distinct: bool = False,
        order_by: object | Sequence[object] | None = None,
    ) -> AggregateFunc[Any]:
        if name.lower() == "count" and not args:
            args = (Star(),)  # count() -> count(*)
        return AggregateFunc(
            name,
            tuple(to_expr(a) for a in args),
            distinct=distinct,
            order_by=tuple(to_column(o) for o in as_tuple(order_by)),
        )

    def __getattr__(self, name: str) -> Callable[..., AggregateFunc[Any]]:
        if name.startswith("__"):
            raise AttributeError(name)
        sql_name = name.rstrip("_")

        def call(
            *args: object,
            distinct: bool = False,
            order_by: object | Sequence[object] | None = None,
        ) -> AggregateFunc[Any]:
            return self(sql_name, *args, distinct=distinct, order_by=order_by)

        return call


func = _FuncNamespace()


# --------------------------------------------------------------------------------------------------------------------
# CASE
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Case[T](Expr[T]):
    subject: Expr[Any] | None = None
    whens: tuple[tuple[Expr[Any], Expr[Any]], ...] = ()
    else_value: Expr[Any] | None = None

    def else_(self, value: Expr[T] | PyScalar) -> Case[T]:
        return Case(self.subject, self.whens, to_expr(value))

    @override
    def build(self) -> Query:
        if not self.whens:
            raise ValueError("CASE requires at least one WHEN")
        return concat(
            "(CASE",
            concat(" ", self.subject) if self.subject is not None else None,
            *(concat(" WHEN ", c, " THEN ", v) for c, v in self.whens),
            concat(" ELSE ", self.else_value) if self.else_value is not None else None,
            " END)",
        )


@dataclass(frozen=True, slots=True, eq=False)
class SearchedCase[T](Case[T]):
    def when(self, condition: Expr[t.Boolean], then: Expr[T] | PyScalar) -> SearchedCase[T]:
        return SearchedCase(self.subject, (*self.whens, (condition, to_expr(then))), self.else_value)


@dataclass(frozen=True, slots=True, eq=False)
class SimpleCase[S, T](Case[T]):
    def when(self, value: Expr[S] | PyScalar, then: Expr[T] | PyScalar) -> SimpleCase[S, T]:
        return SimpleCase(self.subject, (*self.whens, (to_expr(value), to_expr(then))), self.else_value)


@dataclass(frozen=True, slots=True)
class CaseStart:
    """`case()` before the first WHEN; the first THEN value fixes the result type."""

    @overload
    def when[R](self, condition: Expr[t.Boolean], then: Expr[R]) -> SearchedCase[R]: ...
    @overload
    def when(self, condition: Expr[t.Boolean], then: bool) -> SearchedCase[t.Boolean]: ...
    @overload
    def when(self, condition: Expr[t.Boolean], then: int) -> SearchedCase[t.Integer]: ...
    @overload
    def when(self, condition: Expr[t.Boolean], then: float) -> SearchedCase[t.Double]: ...
    @overload
    def when(self, condition: Expr[t.Boolean], then: PyDecimal) -> SearchedCase[t.Decimal]: ...
    @overload
    def when(self, condition: Expr[t.Boolean], then: str) -> SearchedCase[t.Varchar]: ...
    @overload
    def when(self, condition: Expr[t.Boolean], then: datetime.datetime) -> SearchedCase[t.Timestamp]: ...
    @overload
    def when(self, condition: Expr[t.Boolean], then: datetime.date) -> SearchedCase[t.Date]: ...
    @overload
    def when(self, condition: Expr[t.Boolean], then: PyScalar) -> SearchedCase[Any]: ...
    def when(self, condition: Expr[t.Boolean], then: object) -> SearchedCase[Any]:
        return SearchedCase(None, ((condition, to_expr(then)),))


@dataclass(frozen=True, slots=True)
class SimpleCaseStart[S]:
    """`case(subject)` before the first WHEN."""

    subject: Expr[S]

    @overload
    def when[R](self, value: Expr[S] | PyScalar, then: Expr[R]) -> SimpleCase[S, R]: ...
    @overload
    def when(self, value: Expr[S] | PyScalar, then: bool) -> SimpleCase[S, t.Boolean]: ...
    @overload
    def when(self, value: Expr[S] | PyScalar, then: int) -> SimpleCase[S, t.Integer]: ...
    @overload
    def when(self, value: Expr[S] | PyScalar, then: float) -> SimpleCase[S, t.Double]: ...
    @overload
    def when(self, value: Expr[S] | PyScalar, then: str) -> SimpleCase[S, t.Varchar]: ...
    @overload
    def when(self, value: Expr[S] | PyScalar, then: PyScalar) -> SimpleCase[S, Any]: ...
    def when(self, value: object, then: object) -> SimpleCase[S, Any]:
        return SimpleCase(self.subject, ((to_expr(value), to_expr(then)),))


@overload
def case() -> CaseStart: ...
@overload
def case[S](subject: Expr[S]) -> SimpleCaseStart[S]: ...
@overload
def case(subject: PyScalar) -> SimpleCaseStart[Any]: ...
def case(subject: object = ...) -> CaseStart | SimpleCaseStart[Any]:
    """Searched CASE (`case().when(cond, v)`) or simple CASE (`case(x).when(1, "a")`)."""
    if subject is ...:
        return CaseStart()
    return SimpleCaseStart(to_expr(subject))


# --------------------------------------------------------------------------------------------------------------------
# Window specification
# --------------------------------------------------------------------------------------------------------------------


def _bound(value: FrameBound, *, start: bool) -> str:
    if value is None:
        return "UNBOUNDED PRECEDING" if start else "UNBOUNDED FOLLOWING"
    if isinstance(value, datetime.timedelta):
        if not value:
            return "CURRENT ROW"
        return f"{render_literal(abs(value))} {'PRECEDING' if value < datetime.timedelta(0) else 'FOLLOWING'}"
    if value == 0:
        return "CURRENT ROW"
    return f"{abs(int(value))} {'PRECEDING' if value < 0 else 'FOLLOWING'}"


type FrameExclude = Literal["current row", "group", "ties", "no others"]


@dataclass(frozen=True, slots=True, eq=False)
class Frame(Node):
    mode: Literal["ROWS", "RANGE", "GROUPS"]
    start: FrameBound
    end: FrameBound
    exclude: FrameExclude | None = None

    @override
    def build(self) -> Query:
        exclude = f" EXCLUDE {self.exclude.upper()}" if self.exclude is not None else ""
        bounds = f"{_bound(self.start, start=True)} AND {_bound(self.end, start=False)}"
        return Query(f"{self.mode} BETWEEN {bounds}{exclude}")


def rows_between(start: FrameBound, end: FrameBound, *, exclude: FrameExclude | None = None) -> Frame:
    """Frame bounds: `None` = UNBOUNDED, `0` = CURRENT ROW, `-n` = n PRECEDING, `n` = n FOLLOWING.

    `exclude` adds `EXCLUDE CURRENT ROW | GROUP | TIES | NO OTHERS`.
    """
    return Frame("ROWS", start, end, exclude)


def range_between(start: FrameBound, end: FrameBound, *, exclude: FrameExclude | None = None) -> Frame:
    """Like `rows_between`; bounds may also be `timedelta`s (negative = PRECEDING) for date/time ORDER BY."""
    return Frame("RANGE", start, end, exclude)


def groups_between(start: FrameBound, end: FrameBound, *, exclude: FrameExclude | None = None) -> Frame:
    return Frame("GROUPS", start, end, exclude)


@dataclass(frozen=True, slots=True, eq=False)
class Window(Node):
    base: str | None = None
    partition_by: tuple[Expr[Any], ...] = ()
    order_by: tuple[Node, ...] = ()
    frame: Frame | None = None

    @override
    def build(self) -> Query:
        parts: list[Query] = []
        if self.base is not None:
            parts.append(Query(quote_ident(self.base)))
        if self.partition_by:
            parts.append(concat("PARTITION BY ", join(", ", self.partition_by)))
        if self.order_by:
            parts.append(concat("ORDER BY ", join(", ", self.order_by)))
        if self.frame is not None:
            parts.append(self.frame.build())
        return join(" ", parts)


def window(
    *,
    partition_by: object | Sequence[object] | None = None,
    order_by: object | Sequence[object] | None = None,
    frame: Frame | None = None,
) -> Window:
    return _window_spec(None, partition_by, order_by, frame)


@dataclass(frozen=True, slots=True, eq=False)
class Over[T](Expr[T]):
    expr: Node
    window: Window

    @override
    def build(self) -> Query:
        w = self.window
        if w.base is not None and not (w.partition_by or w.order_by or w.frame):
            return concat(self.expr, Query(f" OVER {quote_ident(w.base)}"))
        return concat(self.expr, " OVER (", w, ")")


# --------------------------------------------------------------------------------------------------------------------
# Non-expression nodes used in column lists
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Aliased(Fragment):
    node: Node
    alias: str

    @override
    def build(self) -> Query:
        return concat(self.node, Query(f" AS {quote_ident(self.alias)}"))


@dataclass(frozen=True, slots=True, eq=False)
class OrderItem(Fragment):
    expr: Expr[Any]
    desc: bool = False
    nulls: NullsOrder | None = None

    @override
    def build(self) -> Query:
        return concat(
            self.expr,
            " DESC" if self.desc else " ASC",
            Query(f" NULLS {self.nulls.upper()}") if self.nulls is not None else None,
        )


# --------------------------------------------------------------------------------------------------------------------
# Public constructors
# --------------------------------------------------------------------------------------------------------------------


@overload
def col(name: str, table: str | None = None) -> ColumnRef[Any]: ...
@overload
def col[U](name: str, table: str | None = None, *, type_: DataType[U]) -> ColumnRef[U]: ...
def col(name: str, table: str | None = None, *, type_: DataType[Any] | None = None) -> ColumnRef[Any]:
    """A column reference, optionally qualified by a table name or alias.

    Untyped (`ColumnRef[Any]`) unless `type_` is given: `col("age", type_=dt.INTEGER)` is a `ColumnRef[Integer]`.
    `type_` only affects static typing; nothing is rendered for it.
    """
    del type_
    return ColumnRef(name, (table,) if table is not None else ())


@overload
def val(value: bool) -> Param[t.Boolean]: ...
@overload
def val(value: int) -> Param[t.Integer]: ...
@overload
def val(value: float) -> Param[t.Double]: ...
@overload
def val(value: PyDecimal) -> Param[t.Decimal]: ...
@overload
def val(value: str) -> Param[t.Varchar]: ...
@overload
def val(value: bytes) -> Param[t.Blob]: ...
@overload
def val(value: UUID) -> Param[t.Uuid]: ...
@overload
def val(value: datetime.datetime) -> Param[t.Timestamp]: ...
@overload
def val(value: datetime.date) -> Param[t.Date]: ...
@overload
def val(value: datetime.time) -> Param[t.Time]: ...
@overload
def val(value: datetime.timedelta) -> Param[t.Interval]: ...
@overload
def val(value: BaseGeometry) -> Param[t.Geometry]: ...
@overload
def val(value: object) -> Param[Any]: ...
def val(value: object) -> Param[Any]:
    """A bound parameter, typed from the Python value (e.g. to use a `str` where a column name would be assumed)."""
    return Param(value)


@overload
def lit(value: bool) -> Lit[t.Boolean]: ...
@overload
def lit(value: int) -> Lit[t.Integer]: ...
@overload
def lit(value: float) -> Lit[t.Double]: ...
@overload
def lit(value: PyDecimal) -> Lit[t.Decimal]: ...
@overload
def lit(value: str) -> Lit[t.Varchar]: ...
@overload
def lit(value: bytes) -> Lit[t.Blob]: ...
@overload
def lit(value: UUID) -> Lit[t.Uuid]: ...
@overload
def lit(value: datetime.datetime) -> Lit[t.Timestamp]: ...
@overload
def lit(value: datetime.date) -> Lit[t.Date]: ...
@overload
def lit(value: datetime.time) -> Lit[t.Time]: ...
@overload
def lit(value: datetime.timedelta) -> Lit[t.Interval]: ...
@overload
def lit(value: BaseGeometry) -> Lit[t.Geometry]: ...
@overload
def lit(value: object) -> Lit[Any]: ...
def lit(value: object) -> Lit[Any]:
    """Render a value inline as a SQL literal instead of a parameter."""
    return Lit(value)


def sql(template: Template) -> SQL[Any]:
    """Embed raw SQL from a t-string: `sql(t"date_trunc('day', {ts})")`. Interpolated values are parameters.

    The result is untyped (`Expr[Any]`); cast it (`sql(...).cast(dt.DATE)`) to give it a type.
    """
    return SQL(template)


def keyword(kw: LiteralString) -> Keyword[Any]:
    return Keyword(text(kw).sql)


DEFAULT = Keyword[Any]("DEFAULT")
NULL = Keyword[Any]("NULL")
TRUE = Keyword[t.Boolean]("true")
FALSE = Keyword[t.Boolean]("false")


def make_star(
    qualifier: tuple[str, ...] = (),
    *,
    exclude: Sequence[str] = (),
    replace: dict[str, Expr[Any] | PyScalar] | None = None,
    rename: dict[str, str] | None = None,
    like: str | None = None,
    not_like: str | None = None,
    ilike: str | None = None,
    not_ilike: str | None = None,
    glob: str | None = None,
    similar_to: str | None = None,
) -> Star:
    candidates: tuple[tuple[StarPattern, str | None], ...] = (
        ("LIKE", like),
        ("NOT LIKE", not_like),
        ("ILIKE", ilike),
        ("NOT ILIKE", not_ilike),
        ("GLOB", glob),
        ("SIMILAR TO", similar_to),
    )
    patterns: list[tuple[StarPattern, str]] = [(op, p) for op, p in candidates if p is not None]
    if len(patterns) > 1:
        raise ValueError("Give at most one of like / not_like / ilike / not_ilike / glob / similar_to")
    return Star(
        qualifier,
        tuple(exclude),
        tuple((to_expr(v), k) for k, v in (replace or {}).items()),
        tuple((rename or {}).items()),
        patterns[0] if patterns else None,
    )


def star(
    *,
    exclude: Sequence[str] = (),
    replace: dict[str, Expr[Any] | PyScalar] | None = None,
    rename: dict[str, str] | None = None,
    like: str | None = None,
    not_like: str | None = None,
    ilike: str | None = None,
    not_ilike: str | None = None,
    glob: str | None = None,
    similar_to: str | None = None,
) -> Star:
    """`*` with DuckDB's star modifiers.

    - `exclude=["a"]`              `* EXCLUDE ("a")`
    - `replace={"a": expr}`        `* REPLACE (expr AS "a")`
    - `rename={"a": "b"}`          `* RENAME ("a" AS "b")`
    - `like="num%"`                `* LIKE 'num%'`: keep columns whose name matches (also `not_like`, `ilike`,
                                     `not_ilike`, `glob`, `similar_to`)
    """
    return make_star(
        (),
        exclude=exclude,
        replace=replace,
        rename=rename,
        like=like,
        not_like=not_like,
        ilike=ilike,
        not_ilike=not_ilike,
        glob=glob,
        similar_to=similar_to,
    )


@overload
def columns(selector: Callable[[Expr[t.Varchar]], Expr[t.Boolean]]) -> ColumnsExpr: ...
@overload
def columns(selector: str | Sequence[str] | Star | type[Any] | Node) -> ColumnsExpr: ...
def columns(selector: object) -> ColumnsExpr:
    """DuckDB `COLUMNS(...)`:

    - `columns("num_.*")`                       regex on column names
    - `columns(["id", "name"])`                 a list of names
    - `columns(lambda c: c.like("num%"))`       a lambda over the column name
    - `columns(star(exclude=["name"]))`         a star expression; `columns(User)` / `columns(t)` for `COLUMNS(t.*)`
    """
    if isinstance(selector, str):
        return ColumnsExpr(Lit(selector))
    if isinstance(selector, (list, tuple)):
        return ColumnsExpr(Lit(list(selector)))
    if isinstance(selector, type) and hasattr(selector, "__table__"):
        return ColumnsExpr(Star(selector.__table__.qualifier()))
    if isinstance(selector, Node):
        qualifier: Callable[[], tuple[str, ...]] | None = getattr(selector, "qualifier", None)
        if callable(qualifier) and not isinstance(selector, Expr):  # a FROM source such as table("t")
            return ColumnsExpr(Star(qualifier()))
        return ColumnsExpr(selector)
    if callable(selector):
        return ColumnsExpr(make_lambda(cast_callable(selector)))
    raise TypeError(f"Unsupported COLUMNS selector: {selector!r}")


def positional(n: int) -> PositionalRef:
    """`#n`: the n-th column of the FROM clause (1-based)."""
    return PositionalRef(n)


@overload
def list_comprehension[E, R](
    values: Expr[t.List[E]],
    fn: Callable[[Expr[E]], Expr[R]],
    *,
    where: Callable[[Expr[E]], Expr[t.Boolean]] | None = None,
) -> ListComprehension[t.List[R]]: ...
@overload
def list_comprehension[E, R](
    values: Expr[t.List[E]],
    fn: Callable[[Expr[E], Expr[t.BigInt]], Expr[R]],
    *,
    where: Callable[[Expr[E], Expr[t.BigInt]], Expr[t.Boolean]] | None = None,
) -> ListComprehension[t.List[R]]: ...
def list_comprehension(
    values: Expr[Any],
    fn: Callable[..., Expr[Any]],
    *,
    where: Callable[..., Expr[Any]] | None = None,
) -> ListComprehension[Any]:
    """`[fn(x) FOR x IN values IF where(x)]`. A second lambda parameter is the 1-based index:
    `list_comprehension(xs, lambda x, i: x + i)`."""
    body = make_lambda(fn)
    condition = None
    if where is not None:
        cond = make_lambda(where)
        if cond.names != body.names[: len(cond.names)]:
            raise ValueError("fn and where must use the same parameter names")
        condition = cond.body
    return ListComprehension(values, body.names, body.body, condition)


@overload
def any_[E](values: Expr[t.List[E]]) -> Quantified[E]: ...
@overload
def any_(values: Node) -> Quantified[Any]: ...
def any_(values: Node) -> Quantified[Any]:
    """`x = any_(subquery)` / `x > any_(list_expr)`: true if the comparison holds for any value."""
    return Quantified("ANY", values)


@overload
def all_[E](values: Expr[t.List[E]]) -> Quantified[E]: ...
@overload
def all_(values: Node) -> Quantified[Any]: ...
def all_(values: Node) -> Quantified[Any]:
    """`x > all_(subquery)`: true if the comparison holds for every value."""
    return Quantified("ALL", values)


def try_[T](expr: Expr[T]) -> Try[T]:
    """`TRY(expr)`: NULL instead of raising an error (e.g. on a failed cast)."""
    return Try(expr)


def and_(*conditions: Expr[t.Boolean]) -> Bool:
    if not conditions:
        return TRUE
    result = conditions[0]
    for c in conditions[1:]:
        result = result & c
    return result


def or_(*conditions: Expr[t.Boolean]) -> Bool:
    if not conditions:
        return FALSE
    result = conditions[0]
    for c in conditions[1:]:
        result = result | c
    return result


def not_(condition: Expr[t.Boolean]) -> Bool:
    return ~condition


def exists(query: Node) -> Bool:
    return Exists(query)


def not_exists(query: Node) -> Bool:
    return Exists(query, negate=True)


@overload
def cast[U](value: Expr[Any] | PyScalar, type_: DataType[U]) -> Expr[U]: ...
@overload
def cast(value: Expr[Any] | PyScalar, type_: str) -> Expr[Any]: ...
def cast(value: object, type_: DataType[Any] | str) -> Expr[Any]:
    return to_expr(value).cast(type_)


@overload
def try_cast[U](value: Expr[Any] | PyScalar, type_: DataType[U]) -> Expr[U]: ...
@overload
def try_cast(value: Expr[Any] | PyScalar, type_: str) -> Expr[Any]: ...
def try_cast(value: object, type_: DataType[Any] | str) -> Expr[Any]:
    return to_expr(value).try_cast(type_)
