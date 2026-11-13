from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, override

from parrotlet.expr import Bool, ColumnRef, Expr, Fragment, PyScalar, and_, to_column, to_expr
from parrotlet.query import Node, Query, concat, inline_params, join, qualified, quote_ident, render_literal
from parrotlet.source import CTE, Source

if TYPE_CHECKING:
    from parrotlet.database import Database

type Value = Expr[Any] | PyScalar
"""A SQL value: an expression or a Python value (bound as a parameter)."""

type ColumnInput = Expr[Any] | Fragment | Statement | type[Any] | PyScalar
"""An item in a column list: an expression, `expr.as_()` / `expr.desc()`, a column name (`str`), a subquery, a
Model (`table.*`) or another Python value (bound as a parameter)."""

type FromInput = str | Source | Expr[Any] | type[Any]
"""A FROM / JOIN source: a table name, `table()`, a subquery/CTE, a table-function call or a Model."""


class Statement(Node):
    __slots__ = ()

    @override
    def __str__(self) -> str:
        return self.sql


def with_clause(ctes: tuple[CTE, ...], *, recursive: bool) -> Query | None:
    if not ctes:
        return None
    return concat("WITH RECURSIVE " if recursive else "WITH ", join(", ", (c.definition() for c in ctes)), " ")


def and_where(current: Bool | None, conditions: Iterable[Bool]) -> Bool | None:
    conds = tuple(conditions)
    if not conds:
        return current
    new = and_(*conds)
    return new if current is None else (current & new)


def column_name(key: str | ColumnRef) -> str:
    """The bare column name for SET / INSERT column lists (DuckDB does not accept qualified names there)."""
    return key if isinstance(key, str) else key.name


def assignments(
    values: Mapping[str | ColumnRef[Any], Value] | None,
    kwargs: Mapping[str, Value],
) -> tuple[tuple[str, Expr[Any]], ...]:
    pairs = [*(values or {}).items(), *kwargs.items()]
    return tuple((column_name(k), to_expr(v)) for k, v in pairs)


def render_assignments(pairs: tuple[tuple[str, Expr[Any]], ...]) -> Query:
    return join(", ", (concat(Query(quote_ident(k) + " = "), v) for k, v in pairs))


def returning_clause(items: tuple[Node, ...]) -> Query | None:
    if not items:
        return None
    return concat(" RETURNING ", join(", ", items))


def to_columns(items: Iterable[ColumnInput]) -> tuple[Node, ...]:
    return tuple(to_column(i) for i in items)


# --------------------------------------------------------------------------------------------------------------------
# Helpers for DDL / utility statements
# --------------------------------------------------------------------------------------------------------------------

type ObjectName = str | Sequence[str]
"""A catalog object name: `"name"` or a qualified `("schema", "name")` / `("catalog", "schema", "name")`."""


def object_name(name: ObjectName) -> Query:
    return Query(quote_ident(name) if isinstance(name, str) else qualified(*name))


_OPTION_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

type OptionValue = Expr[Any] | PyScalar | Sequence[str]


def render_option_value(value: object) -> Query:
    if isinstance(value, Node):
        with inline_params():
            return value.build()
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        # identifier lists such as PARTITION_BY (year, month)
        return Query("(" + ", ".join(quote_ident(v) for v in value) + ")")
    return Query(render_literal(value))


def render_options(options: Mapping[str, object], *, sep: str = " ") -> Query | None:
    """`(KEY value, KEY2 value2)` for COPY / ATTACH / EXPORT / CREATE SECRET. Values are rendered as literals."""
    items = [(k, v) for k, v in options.items() if v is not None]
    if not items:
        return None
    parts: list[Query] = []
    for key, value in items:
        if not _OPTION_KEY.fullmatch(key):
            raise ValueError(f"Invalid option name: {key!r}")
        parts.append(Query(key.upper() + sep) + render_option_value(value))
    return concat(" (", join(", ", parts), ")")


@dataclass(frozen=True, slots=True, eq=False)
class SimpleStatement(Statement):
    """A statement assembled from trusted fragments. `inline=True` renders values as literals (for statements that
    DuckDB cannot prepare with parameters, e.g. DDL)."""

    parts: tuple[Node | Query | None, ...]
    inline: bool = False
    _db: Database | None = None

    @override
    def build(self) -> Query:
        with inline_params() if self.inline else nullcontext():
            return concat(*self.parts)
