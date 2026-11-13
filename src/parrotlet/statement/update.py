from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, override

from parrotlet.expr import Bool, ColumnRef, Expr
from parrotlet.query import Node, Query, concat
from parrotlet.source import Table, TableLike, to_from_item, to_table
from parrotlet.statement.base import (
    DmlStatement,
    Filterable,
    FromInput,
    Value,
    assignments,
    clause,
    list_clause,
    render_assignments,
    returning_clause,
    with_clause,
)

if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True, eq=False)
class Update(DmlStatement, Filterable):
    _table: Table
    _set: tuple[tuple[str, Expr[Any]], ...] = ()
    _from: tuple[Node, ...] = ()
    _where: Bool | None = None

    def set(self, values: Mapping[str | ColumnRef[Any], Value] | None = None, /, **kwargs: Value) -> Update:
        """`.set({"a": 1})`, `.set({t.c.a: t.c.a + 1})` or `.set(a=1)`. Plain values are bound as parameters."""
        return replace(self, _set=(*self._set, *assignments(values, kwargs)))

    def from_(self, *items: FromInput) -> Update:
        return replace(self, _from=(*self._from, *(to_from_item(i) for i in items)))

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
            list_clause("FROM", self._from),
            clause("WHERE", self._where),
            returning_clause(self._returning),
        )


def update(table: TableLike) -> Update:
    return Update(to_table(table))
