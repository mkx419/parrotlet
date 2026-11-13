from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Self, cast, override

from parrotlet.expr import Bool, ColumnRef, Expr, Fragment, PyScalar, and_, to_column, to_expr
from parrotlet.query import (
    Node,
    Query,
    concat,
    ident_list,
    inline_params,
    is_identifier,
    join,
    qualified,
    quote_ident,
    render_literal,
)
from parrotlet.source import CTE, Source

if TYPE_CHECKING:
    from parrotlet.database import Database

# region Input types

type Value = Expr[Any] | PyScalar
"""A SQL value: an expression or a Python value (bound as a parameter)."""

type ColumnInput = Expr[Any] | Fragment | Statement | type[Any] | PyScalar
"""An item in a column list: an expression, `expr.as_()` / `expr.desc()`, a column name (`str`), a subquery, a
Model (`table.*`) or another Python value (bound as a parameter)."""

type FromInput = str | Source | Expr[Any] | type[Any]
"""A FROM / JOIN source: a table name, `table()`, a subquery/CTE, a table-function call or a Model."""

# endregion


# region Statement base classes


class Statement(Node):
    __slots__ = ()

    @override
    def __str__(self) -> str:
        return self.sql

    def _replace(self, **changes: object) -> Self:
        """A copy with some fields changed (statements are immutable dataclasses)."""
        return replace(cast("Any", self), **changes)


@dataclass(frozen=True, slots=True, eq=False, kw_only=True)
class BoundStatement(Statement):
    """A statement that remembers the `Database` it was created from (`db.select(...)`), so it runs there."""

    _db: Database | None = None

    @override
    def _database(self) -> Database | None:
        return self._db


class Filterable(Statement):
    """`.where()` for SELECT / UPDATE / DELETE. Subclasses provide the `_where` field."""

    __slots__ = ()
    _where: Bool | None

    def where(self, *conditions: Bool) -> Self:
        """Add conditions; multiple calls/arguments are combined with AND."""
        return self._replace(_where=and_where(self._where, conditions))


@dataclass(frozen=True, slots=True, eq=False, kw_only=True)
class DmlStatement(BoundStatement):
    """Fields and methods shared by INSERT / UPDATE / DELETE / MERGE."""

    _ctes: tuple[CTE, ...] = ()
    _returning: tuple[Node, ...] = ()

    @override
    def _returns_rows(self) -> bool:
        return bool(self._returning)

    def with_(self, *ctes: CTE) -> Self:
        """Add CTEs: `WITH name AS (...) <statement>`."""
        return self._replace(_ctes=(*self._ctes, *ctes))

    def returning(self, *items: ColumnInput) -> Self:
        """`RETURNING ...` (for MERGE, `merge_action` tells which action applied to the row)."""
        return self._replace(_returning=(*self._returning, *to_columns(items)))


# endregion


# region Clause helpers


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


def clause(keyword: str, node: Node | None) -> Query | None:
    """`" WHERE <node>"` style clause, or None when `node` is None."""
    return concat(Query(f" {keyword} "), node) if node is not None else None


def list_clause(keyword: str, items: Sequence[Node]) -> Query | None:
    """`" FROM a, b"` style clause, or None when `items` is empty."""
    return concat(Query(f" {keyword} "), join(", ", items)) if items else None


def column_name(key: str | ColumnRef) -> str:
    """The bare column name for SET / INSERT column lists (DuckDB does not accept qualified names there)."""
    return key if isinstance(key, str) else key.name


def column_names(keys: Iterable[str | ColumnRef]) -> tuple[str, ...]:
    return tuple(column_name(k) for k in keys)


def assignments(
    values: Mapping[str | ColumnRef[Any], Value] | None,
    kwargs: Mapping[str, Value],
) -> tuple[tuple[str, Expr[Any]], ...]:
    pairs = [*(values or {}).items(), *kwargs.items()]
    return tuple((column_name(k), to_expr(v)) for k, v in pairs)


def render_assignments(pairs: tuple[tuple[str, Expr[Any]], ...]) -> Query:
    return join(", ", (concat(Query(quote_ident(k) + " = "), v) for k, v in pairs))


def returning_clause(items: tuple[Node, ...]) -> Query | None:
    return list_clause("RETURNING", items)


def to_columns(items: Iterable[ColumnInput]) -> tuple[Node, ...]:
    return tuple(to_column(i) for i in items)


# endregion


# region Helpers for DDL / utility statements

type ObjectName = str | Sequence[str]
"""A catalog object name: `"name"` or a qualified `("schema", "name")` / `("catalog", "schema", "name")`."""


def object_name(name: ObjectName) -> Query:
    return Query(quote_ident(name) if isinstance(name, str) else qualified(*name))


def create_head(kind: str, *, or_replace: bool = False, temporary: bool = False, if_not_exists: bool = False) -> Query:
    """`CREATE [OR REPLACE] [TEMPORARY] <kind> [IF NOT EXISTS] `."""
    if or_replace and if_not_exists:
        raise ValueError("or_replace and if_not_exists cannot be combined")
    return Query(
        "CREATE "
        + ("OR REPLACE " if or_replace else "")
        + ("TEMPORARY " if temporary else "")
        + kind
        + " "
        + ("IF NOT EXISTS " if if_not_exists else ""),
    )


type OptionValue = Expr[Any] | PyScalar | Sequence[str]


def render_option_value(value: object) -> Query:
    if isinstance(value, Query):
        return value  # a trusted fragment, e.g. a bare keyword such as `TYPE s3`
    if isinstance(value, Node):
        with inline_params():
            return value.build()
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        # identifier lists such as PARTITION_BY (year, month)
        return Query(ident_list(value))
    return Query(render_literal(value))


def render_options(options: Mapping[str, object], *, sep: str = " ") -> Query | None:
    """`(KEY value, KEY2 value2)` for COPY / ATTACH / EXPORT / CREATE SECRET. Values are rendered as literals."""
    items = [(k, v) for k, v in options.items() if v is not None]
    if not items:
        return None
    parts: list[Query] = []
    for key, value in items:
        if not is_identifier(key):
            raise ValueError(f"Invalid option name: {key!r}")
        parts.append(Query(key.upper() + sep) + render_option_value(value))
    return concat(" (", join(", ", parts), ")")


@dataclass(frozen=True, slots=True, eq=False)
class SimpleStatement(BoundStatement):
    """A statement assembled from trusted fragments. `inline=True` renders values as literals (for statements that
    DuckDB cannot prepare with parameters, e.g. DDL)."""

    parts: tuple[Node | Query | None, ...]
    inline: bool = False

    @override
    def build(self) -> Query:
        with inline_params() if self.inline else nullcontext():
            return concat(*self.parts)


# endregion
