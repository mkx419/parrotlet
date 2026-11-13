from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, override

from parrotlet.expr import Bool, ColumnRef, Expr, to_expr
from parrotlet.model import Model
from parrotlet.query import Node, Query, concat, ident_list, join
from parrotlet.source import Table, TableLike, to_table
from parrotlet.statement.base import (
    DmlStatement,
    Value,
    and_where,
    assignments,
    clause,
    column_names,
    render_assignments,
    returning_clause,
    with_clause,
)

if TYPE_CHECKING:
    pass


# region ON CONFLICT


@dataclass(frozen=True, slots=True, eq=False)
class OnConflict(Node):
    target: tuple[str, ...]
    action: Literal["NOTHING", "UPDATE"]
    set_: tuple[tuple[str, Expr[Any]], ...] = ()
    where: Bool | None = None

    @override
    def build(self) -> Query:
        target = (" " + ident_list(self.target)) if self.target else ""
        if self.action == "NOTHING":
            return Query(f" ON CONFLICT{target} DO NOTHING")
        return concat(
            Query(f" ON CONFLICT{target} DO UPDATE SET "),
            render_assignments(self.set_),
            clause("WHERE", self.where),
        )


# endregion


# region INSERT


@dataclass(frozen=True, slots=True, eq=False)
class Insert(DmlStatement):
    _table: Table
    _columns: tuple[str, ...] = ()
    _rows: tuple[tuple[Expr[Any], ...], ...] = ()
    _query: Node | None = None
    _default_values: bool = False
    _by: Literal["NAME", "POSITION"] | None = None
    _or: Literal["REPLACE", "IGNORE"] | None = None
    _conflict: OnConflict | None = None

    # region source rows
    def columns(self, *names: str | ColumnRef) -> Insert:
        return replace(self, _columns=column_names(names))

    def values(self, *rows: Sequence[Value] | Mapping[str, Value] | Model) -> Insert:
        """Add rows as sequences (matching `.columns()`), dicts (column name → value) or Model instances."""
        if not rows:
            raise ValueError("values() needs at least one row")
        columns = self._columns
        out: list[tuple[Expr[Any], ...]] = []

        for item in rows:
            row = item.to_row() if isinstance(item, Model) else item
            if isinstance(row, Mapping):
                if not columns:
                    columns = tuple(row.keys())
                if set(row.keys()) != set(columns):
                    raise ValueError(f"Row keys {sorted(row.keys())} do not match columns {sorted(columns)}")
                out.append(tuple(to_expr(row[c]) for c in columns))
            else:
                if columns and len(row) != len(columns):
                    raise ValueError(f"Row has {len(row)} values but {len(columns)} columns were given")
                out.append(tuple(to_expr(v) for v in row))

        width = {len(r) for r in (*self._rows, *out)}
        if len(width) > 1:
            raise ValueError("All rows must have the same number of values")
        return replace(self, _columns=columns, _rows=(*self._rows, *out), _query=None, _default_values=False)

    def select(self, query: Node) -> Insert:
        """`INSERT INTO t SELECT ...`"""
        return replace(self, _query=query, _rows=(), _default_values=False)

    def default_values(self) -> Insert:
        return replace(self, _default_values=True, _rows=(), _query=None)

    # endregion

    # region DuckDB modifiers
    def by_name(self) -> Insert:
        """DuckDB `INSERT INTO t BY NAME SELECT ...`: match columns by name instead of position."""
        return replace(self, _by="NAME")

    def by_position(self) -> Insert:
        """DuckDB `INSERT INTO t BY POSITION ...` (the default, made explicit)."""
        return replace(self, _by="POSITION")

    def or_replace(self) -> Insert:
        """DuckDB `INSERT OR REPLACE` (needs a primary key / unique constraint)."""
        return replace(self, _or="REPLACE")

    def or_ignore(self) -> Insert:
        """DuckDB `INSERT OR IGNORE`."""
        return replace(self, _or="IGNORE")

    # endregion

    # region ON CONFLICT
    def on_conflict_do_nothing(self, *target: str | ColumnRef) -> Insert:
        return replace(self, _conflict=OnConflict(column_names(target), "NOTHING"))

    def on_conflict_do_update(
        self,
        target: Sequence[str | ColumnRef] | str | ColumnRef,
        set: Mapping[str | ColumnRef[Any], Value] | None = None,  # noqa: A002
        *,
        where: Bool | None = None,
        **kwargs: Value,
    ) -> Insert:
        """`ON CONFLICT (target) DO UPDATE SET ...`. Refer to the proposed row with `excluded.c.<col>`."""
        targets = (target,) if isinstance(target, (str, ColumnRef)) else tuple(target)
        pairs = assignments(set, kwargs)
        if not pairs:
            raise ValueError("on_conflict_do_update needs at least one assignment")
        return replace(
            self,
            _conflict=OnConflict(
                column_names(targets),
                "UPDATE",
                pairs,
                and_where(None, (where,) if where is not None else ()),
            ),
        )

    # endregion

    # region rendering
    @override
    def build(self) -> Query:
        if self._rows:
            source: Query = concat(" VALUES ", join(", ", (concat("(", join(", ", r), ")") for r in self._rows)))
        elif self._query is not None:
            source = concat(" ", self._query)
        elif self._default_values:
            source = Query(" DEFAULT VALUES")
        else:
            raise ValueError("INSERT needs .values(), .select() or .default_values()")

        return concat(
            with_clause(self._ctes, recursive=False),
            Query("INSERT" + (f" OR {self._or}" if self._or else "") + " INTO "),
            self._table.ref(),
            Query(f" BY {self._by}") if self._by else None,
            Query(" " + ident_list(self._columns)) if self._columns else None,
            source,
            self._conflict,
            returning_clause(self._returning),
        )

    # endregion


def insert(table: TableLike, columns: Sequence[str | ColumnRef] = ()) -> Insert:
    """`INSERT INTO table [(columns)] ...`"""
    return Insert(to_table(table), column_names(columns))


excluded = Table("excluded")
"""The proposed row in `ON CONFLICT DO UPDATE`: `excluded.c.price`."""

# endregion
