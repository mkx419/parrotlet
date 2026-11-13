from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, override

from parrotlet.expr import Bool, ColumnRef, Expr
from parrotlet.query import Node, Query, concat, join
from parrotlet.source import CTE, Table, TableLike, to_from_item, to_table
from parrotlet.statement.base import (
    ColumnInput,
    FromInput,
    Statement,
    Value,
    and_where,
    assignments,
    render_assignments,
    returning_clause,
    to_columns,
    with_clause,
)

if TYPE_CHECKING:
    from parrotlet.database import Database


@dataclass(frozen=True, slots=True, eq=False)
class Update(Statement):
    _table: Table
    _set: tuple[tuple[str, Expr[Any]], ...] = ()
    _from: tuple[Node, ...] = ()
    _where: Bool | None = None
    _returning: tuple[Node, ...] = ()
    _ctes: tuple[CTE, ...] = ()
    _db: Database | None = None

    def set(self, values: Mapping[str | ColumnRef[Any], Value] | None = None, /, **kwargs: Value) -> Update:
        """`.set({"a": 1})`, `.set({t.c.a: t.c.a + 1})` or `.set(a=1)`. Plain values are bound as parameters."""
        return replace(self, _set=(*self._set, *assignments(values, kwargs)))

    def from_(self, *items: FromInput) -> Update:
        return replace(self, _from=(*self._from, *(to_from_item(i) for i in items)))

    def where(self, *conditions: Bool) -> Update:
        return replace(self, _where=and_where(self._where, conditions))

    def returning(self, *items: ColumnInput) -> Update:
        return replace(self, _returning=(*self._returning, *to_columns(items)))

    def with_(self, *ctes: CTE) -> Update:
        return replace(self, _ctes=(*self._ctes, *ctes))

    @override
    def build(self) -> Query:
        if not self._set:
            raise ValueError("UPDATE needs at least one .set() assignment")
        return concat(
            with_clause(self._ctes, recursive=False),
            "UPDATE ",
            self._table,
            " SET ",
            render_assignments(self._set),
            concat(" FROM ", join(", ", self._from)) if self._from else None,
            concat(" WHERE ", self._where) if self._where is not None else None,
            returning_clause(self._returning),
        )


def update(table: TableLike) -> Update:
    return Update(to_table(table))
