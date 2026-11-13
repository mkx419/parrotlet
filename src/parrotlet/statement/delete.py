from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, override

from parrotlet.expr import Bool
from parrotlet.query import Node, Query, concat, join
from parrotlet.source import CTE, Table, TableLike, to_from_item, to_table
from parrotlet.statement.base import (
    ColumnInput,
    FromInput,
    SimpleStatement,
    Statement,
    and_where,
    returning_clause,
    to_columns,
    with_clause,
)

if TYPE_CHECKING:
    from parrotlet.database import Database


@dataclass(frozen=True, slots=True, eq=False)
class Delete(Statement):
    _table: Table
    _using: tuple[Node, ...] = ()
    _where: Bool | None = None
    _returning: tuple[Node, ...] = ()
    _ctes: tuple[CTE, ...] = ()
    _db: Database | None = None

    def using(self, *items: FromInput) -> Delete:
        return replace(self, _using=(*self._using, *(to_from_item(i) for i in items)))

    def where(self, *conditions: Bool) -> Delete:
        return replace(self, _where=and_where(self._where, conditions))

    def returning(self, *items: ColumnInput) -> Delete:
        return replace(self, _returning=(*self._returning, *to_columns(items)))

    def with_(self, *ctes: CTE) -> Delete:
        return replace(self, _ctes=(*self._ctes, *ctes))

    @override
    def build(self) -> Query:
        return concat(
            with_clause(self._ctes, recursive=False),
            "DELETE FROM ",
            self._table,
            concat(" USING ", join(", ", self._using)) if self._using else None,
            concat(" WHERE ", self._where) if self._where is not None else None,
            returning_clause(self._returning),
        )


def delete(table: TableLike) -> Delete:
    """`DELETE FROM table`. Without `.where()` this deletes every row."""
    return Delete(to_table(table))


def truncate(table: TableLike) -> SimpleStatement:
    """`TRUNCATE table`: delete every row."""
    return SimpleStatement((Query("TRUNCATE "), to_table(table).ref()))
