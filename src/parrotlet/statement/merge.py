"""DuckDB `MERGE INTO`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal, override

from parrotlet import sqltypes as t
from parrotlet.expr import Bool, ColumnRef, to_expr
from parrotlet.query import Node, Query, concat, join, quote_ident, render_literal
from parrotlet.source import CTE, Table, TableLike, to_from_item, to_table
from parrotlet.statement.base import (
    ColumnInput,
    FromInput,
    Statement,
    Value,
    assignments,
    column_name,
    render_assignments,
    returning_clause,
    to_columns,
    with_clause,
)

if TYPE_CHECKING:
    from parrotlet.database import Database

type WhenKind = Literal["MATCHED", "NOT MATCHED", "NOT MATCHED BY SOURCE"]

merge_action = ColumnRef[t.Varchar]("merge_action")
"""In `MERGE ... RETURNING`: which action applied to the row (`'INSERT'`, `'UPDATE'` or `'DELETE'`)."""


@dataclass(frozen=True, slots=True, eq=False)
class When(Node):
    kind: WhenKind
    condition: Bool | None
    action: Query

    @override
    def build(self) -> Query:
        return concat(
            Query(f" WHEN {self.kind}"),
            concat(" AND ", self.condition) if self.condition is not None else None,
            " THEN ",
            self.action,
        )


def _error(message: str | None) -> Query:
    return Query("ERROR" + (f" {render_literal(message)}" if message is not None else ""))


@dataclass(frozen=True, slots=True)
class _Matched:
    """Actions for `WHEN MATCHED` / `WHEN NOT MATCHED BY SOURCE` (the target row exists)."""

    merge: Merge
    kind: WhenKind
    condition: Bool | None

    def _then(self, action: Query) -> Merge:
        return replace(self.merge, _whens=(*self.merge._whens, When(self.kind, self.condition, action)))

    def update(self, values: Mapping[str | ColumnRef[Any], Value] | None = None, /, **kwargs: Value) -> Merge:
        """`UPDATE SET col = value, ...`"""
        pairs = assignments(values, kwargs)
        if not pairs:
            raise ValueError("update() needs assignments; use update_all() for UPDATE SET *")
        return self._then(concat("UPDATE SET ", render_assignments(pairs)))

    def update_all(self) -> Merge:
        """`UPDATE SET *`: copy every column from the source row (by position)."""
        return self._then(Query("UPDATE SET *"))

    def update_by_name(self) -> Merge:
        """`UPDATE BY NAME`: copy columns from the source row by name."""
        return self._then(Query("UPDATE BY NAME"))

    def delete(self) -> Merge:
        return self._then(Query("DELETE"))

    def do_nothing(self) -> Merge:
        return self._then(Query("DO NOTHING"))

    def error(self, message: str | None = None) -> Merge:
        """`ERROR ['message']`: abort the MERGE if such a row occurs."""
        return self._then(_error(message))


@dataclass(frozen=True, slots=True)
class _NotMatched:
    """Actions for `WHEN NOT MATCHED [BY TARGET]` (the source row has no target row)."""

    merge: Merge
    condition: Bool | None

    def _then(self, action: Query) -> Merge:
        return replace(self.merge, _whens=(*self.merge._whens, When("NOT MATCHED", self.condition, action)))

    def insert(
        self,
        values: Mapping[str, Value] | Sequence[Value],
        columns: Sequence[str | ColumnRef[Any]] = (),
    ) -> Merge:
        """`INSERT (cols) VALUES (...)` from a dict (column → value) or a sequence (with optional `columns`)."""
        if isinstance(values, Mapping):
            cols = tuple(values.keys())
            vals = tuple(to_expr(v) for v in values.values())
        else:
            cols = tuple(column_name(c) for c in columns)
            vals = tuple(to_expr(v) for v in values)
        head = ("INSERT (" + ", ".join(quote_ident(c) for c in cols) + ") VALUES (") if cols else "INSERT VALUES ("
        return self._then(concat(Query(head), join(", ", vals), ")"))

    def insert_all(self) -> Merge:
        """`INSERT *`: insert the source row (by position)."""
        return self._then(Query("INSERT *"))

    def insert_by_name(self) -> Merge:
        """`INSERT BY NAME`: insert the source row matching columns by name."""
        return self._then(Query("INSERT BY NAME"))

    def do_nothing(self) -> Merge:
        return self._then(Query("DO NOTHING"))

    def error(self, message: str | None = None) -> Merge:
        return self._then(_error(message))


@dataclass(frozen=True, slots=True, eq=False)
class Merge(Statement):
    """`MERGE INTO target USING source ON cond WHEN ... THEN ...`

    ```python
    merge_into(User).using(staged, on=User.id == staged.c.id)
        .when_matched().update(name=staged.c.name)
        .when_not_matched().insert_by_name()
        .returning(merge_action, User.id)
    ```
    """

    _target: Table
    _source: Node | None = None
    _on: Bool | None = None
    _using_columns: tuple[str, ...] = ()
    _whens: tuple[When, ...] = ()
    _returning: tuple[Node, ...] = ()
    _ctes: tuple[CTE, ...] = ()
    _db: Database | None = None

    def using(
        self,
        source: FromInput,
        on: Bool | None = None,
        *,
        columns: Sequence[str] | str | None = None,
    ) -> Merge:
        """The source rows, matched with `on=condition` or `columns=` (`USING (col, ...)`)."""
        cols = (columns,) if isinstance(columns, str) else tuple(columns or ())
        if (on is None) == (not cols):
            raise ValueError("Give exactly one of on= or columns=")
        return replace(self, _source=to_from_item(source), _on=on, _using_columns=cols)

    def when_matched(self, condition: Bool | None = None) -> _Matched:
        return _Matched(self, "MATCHED", condition)

    def when_not_matched(self, condition: Bool | None = None) -> _NotMatched:
        """`WHEN NOT MATCHED [BY TARGET]`: source rows without a target row."""
        return _NotMatched(self, condition)

    def when_not_matched_by_source(self, condition: Bool | None = None) -> _Matched:
        """`WHEN NOT MATCHED BY SOURCE`: target rows without a source row."""
        return _Matched(self, "NOT MATCHED BY SOURCE", condition)

    def returning(self, *items: ColumnInput) -> Merge:
        """`RETURNING ...`; `merge_action` tells which action applied."""
        return replace(self, _returning=(*self._returning, *to_columns(items)))

    def with_(self, *ctes: CTE) -> Merge:
        return replace(self, _ctes=(*self._ctes, *ctes))

    @override
    def build(self) -> Query:
        if self._source is None:
            raise ValueError("MERGE needs .using(source, on=...)")
        if not self._whens:
            raise ValueError("MERGE needs at least one WHEN clause")
        match = (
            concat(" ON ", self._on)
            if self._on is not None
            else Query(" USING (" + ", ".join(quote_ident(c) for c in self._using_columns) + ")")
        )
        return concat(
            with_clause(self._ctes, recursive=False),
            "MERGE INTO ",
            self._target,
            " USING ",
            self._source,
            match,
            *self._whens,
            returning_clause(self._returning),
        )


def merge_into(target: TableLike) -> Merge:
    return Merge(to_table(target))
