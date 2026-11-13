"""DuckDB's PIVOT / UNPIVOT statements (usable on their own or as subqueries)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, override

from parrotlet.expr import Expr, NullsOrder, to_expr
from parrotlet.query import Node, Query, concat, join, quote_ident, unqualified_columns
from parrotlet.source import CTE, to_from_item
from parrotlet.statement.base import ColumnInput, FromInput, Statement, Value, to_columns, with_clause
from parrotlet.statement.select import QueryStatement

if TYPE_CHECKING:
    from parrotlet.database import Database


def _source(value: FromInput | Statement) -> Query:
    if isinstance(value, Statement):
        return concat("(", value, ")")
    return to_from_item(value).build()


@dataclass(frozen=True, slots=True, eq=False)
class PivotOn(Node):
    column: Node
    values: tuple[Expr[Any], ...] | None = None

    @override
    def build(self) -> Query:
        if self.values is None:
            return self.column.build()
        return concat(self.column, " IN (", join(", ", self.values), ")")


@dataclass(frozen=True, slots=True, eq=False)
class Pivot(QueryStatement):
    """`PIVOT source ON col [IN (...)] USING agg [AS name] GROUP BY ...`

    Without `values=`, DuckDB finds the distinct values itself (the output columns are then data-dependent).
    Column references are rendered unqualified, as PIVOT requires.
    """

    _source: FromInput | Statement
    _on: tuple[PivotOn, ...] = ()
    _using: tuple[Node, ...] = ()
    _group_by: tuple[Node, ...] = ()
    _ctes: tuple[CTE, ...] = ()
    _recursive: bool = False
    _order_by: tuple[Node, ...] | Literal["ALL"] = ()
    _order_all: tuple[bool, NullsOrder | None] = (False, None)
    _limit: Expr[Any] | None = None
    _limit_percent: bool = False
    _offset: Expr[Any] | None = None
    _db: Database | None = None

    def on(self, column: ColumnInput, values: Sequence[Value] | None = None) -> Pivot:
        """Pivot on `column` (one output column per value); call repeatedly for several ON columns."""
        (node,) = to_columns([column])
        vals = tuple(to_expr(v) for v in values) if values is not None else None
        return replace(self, _on=(*self._on, PivotOn(node, vals)))

    def using(self, *aggregates: ColumnInput) -> Pivot:
        """Aggregates for the cells, e.g. `F.sum(t.v)` or `F.sum(t.v).as_("total")`."""
        return replace(self, _using=(*self._using, *to_columns(aggregates)))

    def group_by(self, *columns: ColumnInput) -> Pivot:
        return replace(self, _group_by=(*self._group_by, *to_columns(columns)))

    @override
    def build(self) -> Query:
        if not self._on:
            raise ValueError("PIVOT needs at least one .on(...) column")
        with unqualified_columns():
            body = concat(
                " ON ",
                join(", ", self._on),
                concat(" USING ", join(", ", self._using)) if self._using else None,
                concat(" GROUP BY ", join(", ", self._group_by)) if self._group_by else None,
                self._tail(),
            )
        return concat(with_clause(self._ctes, recursive=self._recursive), "PIVOT ", _source(self._source), body)


@dataclass(frozen=True, slots=True, eq=False)
class Unpivot(QueryStatement):
    """`UNPIVOT source ON col1, col2 INTO NAME name VALUE value` (ON also takes `columns("regex")`)."""

    _source: FromInput | Statement
    _on: tuple[Node, ...] = ()
    _name: str = "name"
    _value: tuple[str, ...] = ("value",)
    _ctes: tuple[CTE, ...] = ()
    _recursive: bool = False
    _order_by: tuple[Node, ...] | Literal["ALL"] = ()
    _order_all: tuple[bool, NullsOrder | None] = (False, None)
    _limit: Expr[Any] | None = None
    _limit_percent: bool = False
    _offset: Expr[Any] | None = None
    _db: Database | None = None

    def on(self, *columns: ColumnInput) -> Unpivot:
        return replace(self, _on=(*self._on, *to_columns(columns)))

    def into(self, *, name: str, value: str | Sequence[str]) -> Unpivot:
        """Names of the output columns holding the former column name and its value."""
        return replace(self, _name=name, _value=(value,) if isinstance(value, str) else tuple(value))

    @override
    def build(self) -> Query:
        if not self._on:
            raise ValueError("UNPIVOT needs at least one .on(...) column")
        into = f" INTO NAME {quote_ident(self._name)} VALUE " + ", ".join(quote_ident(v) for v in self._value)
        return concat(
            with_clause(self._ctes, recursive=self._recursive),
            "UNPIVOT ",
            _source(self._source),
            " ON ",
            join(", ", self._on),
            Query(into),
            self._tail(),
        )


def pivot(source: FromInput | Statement) -> Pivot:
    """Start a PIVOT: `pivot(Sales).on(Sales.month).using(F.sum(Sales.amount)).group_by(Sales.region)`."""
    return Pivot(source)


def unpivot(source: FromInput | Statement) -> Unpivot:
    """Start an UNPIVOT: `unpivot(Wide).on(columns("m_.*")).into(name="month", value="amount")`."""
    return Unpivot(source)
