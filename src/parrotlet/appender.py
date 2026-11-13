"""Typed wrapper over DuckDB's native appender (bulk insert / upsert / update / delete)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, Self, cast

from shapely.geometry.base import BaseGeometry

from parrotlet.expr import ColumnRef, Keyword
from parrotlet.model import Model
from parrotlet.source import TableLike, model_table, to_table
from parrotlet.statement.base import column_name

if TYPE_CHECKING:
    from types import TracebackType

    import duckdb

    from parrotlet.model import Column

type AppendAction = Literal["insert", "upsert", "update", "delete"]
type ColumnName = str | ColumnRef[Any]


def _convert(value: object) -> object:
    """Python values the native appender cannot take directly."""
    if isinstance(value, BaseGeometry):
        return value.wkb  # stored into GEOMETRY columns from WKB
    if isinstance(value, Keyword):
        raise ValueError(
            "The appender cannot insert DEFAULT; leave database-side default columns out of `columns` "
            "(the default for models) or give the row a value",
        )
    return value


class Appender[R]:
    """Buffers rows and writes them with DuckDB's appender: much faster than INSERT for many rows.

    ```python
    with db.appender(User) as app:          # flushed when the block exits normally
        app.append(User(id=1, name="alice"))
        app.extend(users)

    with db.appender(User, action="upsert") as app: ...                    # insert or replace by primary key
    with db.appender(User, action="update", columns=[User.id, User.age]) as app: ...   # update by key
    with db.appender(User, action="delete") as app:                        # delete by key
        app.append(User(id=3, name="x"))    # only the key is used
    ```

    Rows may be Model instances (for a Model target), mappings (column name → value) or sequences (in `columns`
    order). For a Model target, `columns` defaults to the columns that hold values: generated columns and columns with a
    database-side default (`column(default=fn.now())`) are left out so that DuckDB fills them in. `key` defaults to the
    primary key. `batch_size` flushes automatically every that many rows.
    """

    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        table: TableLike,
        *,
        columns: Sequence[ColumnName] | None = None,
        action: AppendAction = "insert",
        key: Sequence[ColumnName] | None = None,
        batch_size: int | None = None,
    ) -> None:
        tbl = to_table(table)
        self.model: type[Model] | None = cast("type[Model]", table) if model_table(table) is not None else None
        self.action = action
        self.batch_size = batch_size
        self._pending = 0

        model_columns: tuple[Column[Any], ...] = self.model.__columns__ if self.model is not None else ()
        if key is None and self.model is not None and action in ("update", "delete"):
            key_names = [c.name for c in model_columns if c.primary_key]
        else:
            key_names = [column_name(k) for k in key or ()]
        if columns is not None:
            column_names = [column_name(c) for c in columns]
        elif self.model is not None:
            column_names = [c.name for c in model_columns if c.generated is None and not c.has_server_default()]
        else:
            column_names = []

        if action == "delete":
            if not key_names:
                raise ValueError("The delete action needs key columns (key=..., or a Model with a primary key)")
            column_names = key_names  # a delete appender buffers exactly its key columns
        if action == "upsert" and key_names:
            raise ValueError("The upsert action matches on the table's primary key / unique constraints; omit key=")
        if action == "update" and not key_names:
            raise ValueError("The update action needs key columns (key=..., or a Model with a primary key)")

        self.columns: tuple[str, ...] = tuple(column_names)
        name = tbl.name if tbl.schema is None else f"{tbl.schema}.{tbl.name}"
        options: dict[str, Any] = {"action": action}
        if action != "delete" and self.columns:
            options["columns"] = list(self.columns)
        if key_names and action in ("update", "delete"):
            options["key"] = key_names
        self._native = connection.appender(name, **options)

    # region rows
    def _values(self, row: R | Mapping[str, Any] | Sequence[Any]) -> tuple[object, ...]:
        if isinstance(row, Model):
            data = row.to_row()
            for column in row.__columns__:
                if (
                    column.name not in self.columns
                    and column.has_server_default()
                    and not isinstance(data[column.name], Keyword)
                ):
                    raise ValueError(
                        f"{column.name!r} has a value but is not appended (database-side default); pass columns=...",
                    )
            return tuple(_convert(data[c]) for c in self.columns)
        if isinstance(row, Mapping):
            mapping = cast("Mapping[str, Any]", row)
            if not self.columns:
                raise ValueError("Mapping rows need columns=... for a table that is not a Model")
            missing = [c for c in self.columns if c not in mapping]
            if missing:
                raise ValueError(f"Row is missing columns {missing}")
            return tuple(_convert(mapping[c]) for c in self.columns)
        return tuple(_convert(v) for v in cast("Sequence[Any]", row))

    def append(self, row: R | Mapping[str, Any] | Sequence[Any]) -> None:
        """Buffer one row."""
        self._native.append_row(*self._values(row))
        self._count(1)

    def extend(self, rows: Iterable[R | Mapping[str, Any] | Sequence[Any]]) -> None:
        """Buffer many rows."""
        for row in rows:
            self.append(row)

    def _count(self, n: int) -> None:
        self._pending += n
        if self.batch_size is not None and self._pending >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        """Write the buffered rows (one statement)."""
        self._native.flush()
        self._pending = 0

    def clear(self) -> None:
        """Drop the buffered rows without writing them."""
        self._native.clear()
        self._pending = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.flush()
        else:
            self.clear()

    # endregion
