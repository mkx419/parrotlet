from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, override

from parrotlet.expr import Bool
from parrotlet.query import Node, Query, concat
from parrotlet.source import Table, TableLike, to_from_item, to_table
from parrotlet.statement.base import (
    DmlStatement,
    Filterable,
    FromInput,
    SimpleStatement,
    clause,
    list_clause,
    returning_clause,
    with_clause,
)

if TYPE_CHECKING:
    pass


@dataclass(frozen=True, slots=True, eq=False)
class Delete(DmlStatement, Filterable):
    _table: Table
    _using: tuple[Node, ...] = ()
    _where: Bool | None = None

    def using(self, *items: FromInput) -> Delete:
        return replace(self, _using=(*self._using, *(to_from_item(i) for i in items)))

    @override
    def build(self) -> Query:
        return concat(
            with_clause(self._ctes, recursive=False),
            "DELETE FROM ",
            self._table,
            list_clause("USING", self._using),
            clause("WHERE", self._where),
            returning_clause(self._returning),
        )


def delete(table: TableLike) -> Delete:
    """`DELETE FROM table`. Without `.where()` this deletes every row."""
    return Delete(to_table(table))


def truncate(table: TableLike) -> SimpleStatement:
    """`TRUNCATE table`: delete every row."""
    return SimpleStatement((Query("TRUNCATE "), to_table(table).ref()))
