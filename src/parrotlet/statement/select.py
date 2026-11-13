from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, Self, cast, override

from parrotlet import sqltypes as t
from parrotlet.expr import Bool, Expr, Fragment, NullsOrder, Window, to_column, to_column_expr, to_expr
from parrotlet.query import Node, Query, concat, join, quote_ident
from parrotlet.source import CTE, Sample, SubqueryRef, to_from_item
from parrotlet.statement.base import ColumnInput, FromInput, Statement, and_where, to_columns, with_clause

if TYPE_CHECKING:
    from parrotlet.database import Database

type JoinKind = Literal["INNER", "LEFT", "RIGHT", "FULL", "CROSS", "SEMI", "ANTI", "POSITIONAL", "ASOF", "ASOF LEFT"]
type SetOp = Literal[
    "UNION",
    "UNION ALL",
    "UNION BY NAME",
    "UNION ALL BY NAME",
    "INTERSECT",
    "INTERSECT ALL",
    "EXCEPT",
    "EXCEPT ALL",
]


# --------------------------------------------------------------------------------------------------------------------
# Clause nodes
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Join(Node):
    kind: JoinKind
    target: Node
    on: Bool | None = None
    using: tuple[str, ...] = ()
    natural: bool = False

    @override
    def build(self) -> Query:
        head = ("NATURAL " if self.natural else "") + self.kind + " JOIN "
        if self.on is not None:
            tail: Query | None = concat(" ON ", self.on)
        elif self.using:
            tail = Query(" USING (" + ", ".join(quote_ident(c) for c in self.using) + ")")
        else:
            tail = None
        return concat(" ", Query(head), self.target, tail)


@dataclass(frozen=True, slots=True, eq=False)
class Grouping(Fragment):
    """`ROLLUP (...)`, `CUBE (...)`, `GROUPING SETS (...)` inside GROUP BY."""

    kind: Literal["ROLLUP", "CUBE", "GROUPING SETS"]
    items: tuple[tuple[Node, ...], ...]

    @override
    def build(self) -> Query:
        if self.kind == "GROUPING SETS":
            body = join(", ", (concat("(", join(", ", s), ")") for s in self.items))
        else:
            body = join(", ", (s[0] for s in self.items))
        return concat(Query(self.kind + " ("), body, ")")


def rollup(*columns: ColumnInput) -> Grouping:
    return Grouping("ROLLUP", tuple((to_column(c),) for c in columns))


def cube(*columns: ColumnInput) -> Grouping:
    return Grouping("CUBE", tuple((to_column(c),) for c in columns))


def grouping_sets(*sets: Sequence[ColumnInput]) -> Grouping:
    return Grouping("GROUPING SETS", tuple(tuple(to_column(c) for c in s) for s in sets))


# --------------------------------------------------------------------------------------------------------------------
# Shared behaviour for SELECT and compound (UNION ...) queries
# --------------------------------------------------------------------------------------------------------------------


class QueryStatement(Statement):
    """Methods shared by `Select` and `Compound`. Subclasses provide the fields used here."""

    __slots__ = ()
    _ctes: tuple[CTE, ...]
    _recursive: bool
    _order_by: tuple[Node, ...] | Literal["ALL"]
    _order_all: tuple[bool, NullsOrder | None]
    _limit: Expr[Any] | None
    _limit_percent: bool
    _offset: Expr[Any] | None

    def _replace(self, **changes: object) -> Self:
        return replace(cast("Any", self), **changes)

    # WITH ---------------------------------------------------------------------------------------------------------
    def with_(self, *ctes: CTE) -> Self:
        return self._replace(_ctes=(*self._ctes, *ctes))

    def with_recursive(self, *ctes: CTE) -> Self:
        return self._replace(_ctes=(*self._ctes, *ctes), _recursive=True)

    # ORDER BY / LIMIT ---------------------------------------------------------------------------------------------
    def order_by(self, *items: ColumnInput) -> Self:
        current = () if self._order_by == "ALL" else self._order_by
        return self._replace(_order_by=(*current, *to_columns(items)))

    def order_by_all(self, *, desc: bool = False, nulls: NullsOrder | None = None) -> Self:
        return self._replace(_order_by="ALL", _order_all=(desc, nulls))

    def limit(
        self,
        n: Expr[t.Numeric] | float,
        offset: Expr[t.BigInt] | int | None = None,
        *,
        percent: bool = False,
    ) -> Self:
        """`LIMIT n [OFFSET m]`; `percent=True` renders DuckDB's `LIMIT n%` (a percentage of the rows)."""
        new = self._replace(_limit=to_expr(n), _limit_percent=percent)
        return new if offset is None else new.offset(offset)

    def offset(self, n: Expr[t.BigInt] | int) -> Self:
        return self._replace(_offset=to_expr(n))

    # set operations -----------------------------------------------------------------------------------------------
    def union(self, other: QueryStatement, *, all: bool = False, by_name: bool = False) -> Compound:  # noqa: A002
        op = "UNION" + (" ALL" if all else "") + (" BY NAME" if by_name else "")
        return Compound.of(self, op, other)

    def union_all(self, other: QueryStatement) -> Compound:
        return self.union(other, all=True)

    def intersect(self, other: QueryStatement, *, all: bool = False) -> Compound:  # noqa: A002
        return Compound.of(self, "INTERSECT ALL" if all else "INTERSECT", other)

    def except_(self, other: QueryStatement, *, all: bool = False) -> Compound:  # noqa: A002
        return Compound.of(self, "EXCEPT ALL" if all else "EXCEPT", other)

    # wrapping -----------------------------------------------------------------------------------------------------
    def subquery(self, alias: str, *, lateral: bool = False, columns: Sequence[str] = ()) -> SubqueryRef:
        """Use this query as a FROM / JOIN source (`columns` renames its output columns: `AS alias(c1, c2)`)."""
        return SubqueryRef(self, alias, lateral, tuple(columns))

    def cte(
        self,
        name: str,
        *,
        columns: Sequence[str] = (),
        materialized: bool | None = None,
        using_key: Sequence[str] = (),
    ) -> CTE:
        """Turn this query into a named CTE for `.with_()`.

        `using_key` gives a recursive CTE DuckDB's `USING KEY (...)` semantics (rows with the same key are replaced).
        """
        return CTE(name, self, tuple(columns), materialized, tuple(using_key))

    def scalar(self) -> Expr[Any]:
        """Use this query as a scalar subquery expression."""
        return to_expr(self)

    # rendering ----------------------------------------------------------------------------------------------------
    def _tail(self) -> Query:
        order: Query | None
        if self._order_by == "ALL":
            desc, nulls = self._order_all
            order = Query(
                " ORDER BY ALL" + (" DESC" if desc else " ASC") + (f" NULLS {nulls.upper()}" if nulls else ""),
            )
        elif self._order_by:
            order = concat(" ORDER BY ", join(", ", self._order_by))
        else:
            order = None
        return concat(
            order,
            concat(" LIMIT ", self._limit, "%" if self._limit_percent else None) if self._limit is not None else None,
            concat(" OFFSET ", self._offset) if self._offset is not None else None,
        )


# --------------------------------------------------------------------------------------------------------------------
# SELECT
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Select(QueryStatement):
    _columns: tuple[Node, ...] = ()
    _distinct: bool = False
    _distinct_on: tuple[Expr[Any], ...] = ()
    _from: tuple[Node, ...] = ()
    _joins: tuple[Join, ...] = ()
    _where: Bool | None = None
    _group_by: tuple[Node, ...] | Literal["ALL"] = ()
    _having: Bool | None = None
    _windows: tuple[tuple[str, Window], ...] = ()
    _qualify: Bool | None = None
    _sample: Sample | None = None
    _ctes: tuple[CTE, ...] = ()
    _recursive: bool = False
    _order_by: tuple[Node, ...] | Literal["ALL"] = ()
    _order_all: tuple[bool, NullsOrder | None] = (False, None)
    _limit: Expr[Any] | None = None
    _limit_percent: bool = False
    _offset: Expr[Any] | None = None
    _db: Database | None = None

    # SELECT list --------------------------------------------------------------------------------------------------
    def select(self, *columns: ColumnInput) -> Select:
        """Append columns to the select list."""
        return replace(self, _columns=(*self._columns, *to_columns(columns)))

    def distinct(self, *, on: ColumnInput | Sequence[ColumnInput] | None = None) -> Select:
        """`SELECT DISTINCT`, or `SELECT DISTINCT ON (...)` when `on` is given."""
        if on is None:
            return replace(self, _distinct=True)
        items = on if isinstance(on, (list, tuple)) else (on,)
        return replace(self, _distinct=True, _distinct_on=tuple(to_column_expr(o) for o in items))

    # FROM / JOIN --------------------------------------------------------------------------------------------------
    def from_(self, *items: FromInput) -> Select:
        """Tables (`str` = table name), `table(...)`, `.subquery(alias)`, CTEs, or table-function calls."""
        return replace(self, _from=(*self._from, *(to_from_item(i) for i in items)))

    def _join(
        self,
        kind: JoinKind,
        target: FromInput,
        on: Bool | None,
        using: Sequence[str] | str | None,
        *,
        natural: bool = False,
    ) -> Select:
        using_t = (using,) if isinstance(using, str) else tuple(using or ())
        if on is not None and using_t:
            raise ValueError("Specify either on= or using=, not both")
        return replace(self, _joins=(*self._joins, Join(kind, to_from_item(target), on, using_t, natural)))

    def join(self, target: FromInput, on: Bool | None = None, *, using: Sequence[str] | str | None = None) -> Select:
        return self._join("INNER", target, on, using)

    def left_join(
        self,
        target: FromInput,
        on: Bool | None = None,
        *,
        using: Sequence[str] | str | None = None,
    ) -> Select:
        return self._join("LEFT", target, on, using)

    def right_join(
        self,
        target: FromInput,
        on: Bool | None = None,
        *,
        using: Sequence[str] | str | None = None,
    ) -> Select:
        return self._join("RIGHT", target, on, using)

    def full_join(
        self,
        target: FromInput,
        on: Bool | None = None,
        *,
        using: Sequence[str] | str | None = None,
    ) -> Select:
        return self._join("FULL", target, on, using)

    def cross_join(self, target: FromInput) -> Select:
        return self._join("CROSS", target, None, None)

    def natural_join(self, target: FromInput) -> Select:
        return self._join("INNER", target, None, None, natural=True)

    def semi_join(
        self,
        target: FromInput,
        on: Bool | None = None,
        *,
        using: Sequence[str] | str | None = None,
    ) -> Select:
        return self._join("SEMI", target, on, using)

    def anti_join(
        self,
        target: FromInput,
        on: Bool | None = None,
        *,
        using: Sequence[str] | str | None = None,
    ) -> Select:
        return self._join("ANTI", target, on, using)

    def asof_join(self, target: FromInput, on: Bool, *, left: bool = False) -> Select:
        """DuckDB `ASOF JOIN`: `on` must contain one inequality (e.g. `t.ts >= p.ts`)."""
        return self._join("ASOF LEFT" if left else "ASOF", target, on, None)

    def positional_join(self, target: FromInput) -> Select:
        return self._join("POSITIONAL", target, None, None)

    # filtering / grouping -----------------------------------------------------------------------------------------
    def where(self, *conditions: Bool) -> Select:
        """Add conditions; multiple calls/arguments are combined with AND."""
        return replace(self, _where=and_where(self._where, conditions))

    def group_by(self, *items: ColumnInput) -> Select:
        current = () if self._group_by == "ALL" else self._group_by
        return replace(self, _group_by=(*current, *to_columns(items)))

    def group_by_all(self) -> Select:
        return replace(self, _group_by="ALL")

    def having(self, *conditions: Bool) -> Select:
        return replace(self, _having=and_where(self._having, conditions))

    def window(self, name: str, spec: Window) -> Select:
        """Define a named window (`WINDOW name AS (...)`) to use with `expr.over("name")`."""
        return replace(self, _windows=(*self._windows, (name, spec)))

    def qualify(self, *conditions: Bool) -> Select:
        """DuckDB `QUALIFY`: filter on window function results."""
        return replace(self, _qualify=and_where(self._qualify, conditions))

    def using_sample(
        self,
        *,
        percent: float | None = None,
        rows: int | None = None,
        method: Literal["reservoir", "bernoulli", "system"] | None = None,
        seed: int | None = None,
    ) -> Select:
        sample = Sample.of(percent, rows, method, seed, kind="USING SAMPLE")
        return replace(self, _sample=sample)

    # rendering ----------------------------------------------------------------------------------------------------
    @override
    def build(self) -> Query:
        if self._distinct_on:
            distinct: Query | None = concat("DISTINCT ON (", join(", ", self._distinct_on), ") ")
        elif self._distinct:
            distinct = Query("DISTINCT ")
        else:
            distinct = None

        if self._group_by == "ALL":
            group_by: Query | None = Query(" GROUP BY ALL")
        elif self._group_by:
            group_by = concat(" GROUP BY ", join(", ", self._group_by))
        else:
            group_by = None

        windows = (
            concat(" WINDOW ", join(", ", (concat(Query(quote_ident(n) + " AS ("), w, ")") for n, w in self._windows)))
            if self._windows
            else None
        )

        return concat(
            with_clause(self._ctes, recursive=self._recursive),
            "SELECT ",
            distinct,
            join(", ", self._columns) if self._columns else Query("*"),
            concat(" FROM ", join(", ", self._from)) if self._from else None,
            *self._joins,
            concat(" WHERE ", self._where) if self._where is not None else None,
            group_by,
            concat(" HAVING ", self._having) if self._having is not None else None,
            windows,
            concat(" QUALIFY ", self._qualify) if self._qualify is not None else None,
            self._sample,
            self._tail(),
        )


# --------------------------------------------------------------------------------------------------------------------
# UNION / INTERSECT / EXCEPT
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Compound(QueryStatement):
    _first: Node
    _rest: tuple[tuple[SetOp, Node], ...] = ()
    _ctes: tuple[CTE, ...] = ()
    _recursive: bool = False
    _order_by: tuple[Node, ...] | Literal["ALL"] = ()
    _order_all: tuple[bool, NullsOrder | None] = (False, None)
    _limit: Expr[Any] | None = None
    _limit_percent: bool = False
    _offset: Expr[Any] | None = None
    _db: Database | None = None

    @staticmethod
    def of(left: QueryStatement, op: SetOp, right: QueryStatement) -> Compound:
        # Chain onto an existing compound unless it already has its own ORDER BY / LIMIT / WITH.
        if isinstance(left, Compound) and not (left._order_by or left._limit or left._offset or left._ctes):
            return replace(left, _rest=(*left._rest, (op, right)))
        return Compound(left, ((op, right),), _db=getattr(left, "_db", None) or getattr(right, "_db", None))

    @override
    def build(self) -> Query:
        parts = [concat("(", self._first, ")")]
        for op, q in self._rest:
            parts.append(concat(Query(f" {op} ("), q, ")"))
        return concat(with_clause(self._ctes, recursive=self._recursive), *parts, self._tail())


def select(*columns: ColumnInput) -> Select:
    """Start a SELECT. `str` items are column names, `"*"` is `*`; omit columns for `SELECT *`."""
    return Select(_columns=to_columns(columns))


def from_(*items: FromInput) -> Select:
    """DuckDB's FROM-first syntax: `from_("t")` is `SELECT * FROM t`."""
    return Select().from_(*items)
