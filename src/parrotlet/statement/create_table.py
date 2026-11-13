from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, override

from parrotlet.model import Column, Model
from parrotlet.query import Node, Query, concat, inline_params, join, unqualified_columns
from parrotlet.source import Table, TableLike, to_table
from parrotlet.statement.base import Statement

if TYPE_CHECKING:
    from parrotlet.database import Database


@dataclass(frozen=True, slots=True, eq=False)
class CreateTable(Statement):
    _table: Table
    _columns: tuple[Column, ...] = ()
    _constraints: tuple[Node, ...] = ()
    _or_replace: bool = False
    _if_not_exists: bool = False
    _temporary: bool = False
    _as: Node | None = None
    _db: Database | None = None

    def or_replace(self) -> CreateTable:
        return replace(self, _or_replace=True)

    def if_not_exists(self) -> CreateTable:
        return replace(self, _if_not_exists=True)

    def temporary(self) -> CreateTable:
        return replace(self, _temporary=True)

    def as_(self, query: Node) -> CreateTable:
        """`CREATE TABLE t AS SELECT ...` (the model's columns, if any, are not rendered)."""
        return replace(self, _as=query)

    @override
    def build(self) -> Query:
        if self._or_replace and self._if_not_exists:
            raise ValueError("OR REPLACE and IF NOT EXISTS cannot be combined")

        head = Query(
            "CREATE "
            + ("OR REPLACE " if self._or_replace else "")
            + ("TEMPORARY " if self._temporary else "")
            + "TABLE "
            + ("IF NOT EXISTS " if self._if_not_exists else ""),
        )
        if self._as is not None:
            # CTAS keeps parameters: DuckDB binds them in the SELECT.
            return concat(head, self._table.ref(), " AS ", self._as)
        if not self._columns:
            raise ValueError("CREATE TABLE needs a Model with columns, or .as_(query)")

        # DDL cannot take `?` parameters, so DEFAULT / CHECK values are rendered as literals. Columns in CHECK /
        # GENERATED expressions all belong to this table, so they are rendered without a qualifier.
        with inline_params(), unqualified_columns():
            body = join(", ", (*(c.definition() for c in self._columns), *self._constraints))
        return concat(head, self._table.ref(), " (", body, ")")


def create_table(target: TableLike) -> CreateTable:
    """`CREATE TABLE` from a `Model` class. Pass a table name instead for `create_table("t").as_(select(...))`."""
    if not (isinstance(target, type) and issubclass(target, Model)):
        return CreateTable(to_table(target))
    table = target.__table__
    return CreateTable(
        Table(table.name, table.schema, table.catalog),
        target.__columns__,
        tuple(target.constraints()),
    )
