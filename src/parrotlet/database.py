"""`Database`: a DuckDB connection that statements are bound to, plus model registration."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from string.templatelib import Template
from typing import TYPE_CHECKING, Any, Self, overload

import duckdb

from parrotlet.appender import AppendAction, Appender, ColumnName
from parrotlet.execution import ensure_extensions
from parrotlet.query import Node, PathLike, Query, RawSQL, path_str
from parrotlet.statement import (
    CreateTable,
    Delete,
    Insert,
    Merge,
    Pivot,
    Select,
    Unpivot,
    Update,
    create_table,
    delete,
    from_,
    insert,
    merge_into,
    pivot,
    select,
    truncate,
    unpivot,
    update,
)
from parrotlet.statement.base import SimpleStatement

if TYPE_CHECKING:
    from types import TracebackType

    from parrotlet.model import Model
    from parrotlet.source import Table, TableLike
    from parrotlet.statement.base import BoundStatement, ColumnInput, FromInput, Statement


class Database:
    """A DuckDB database; statements created from it run on it without passing a connection.

    ```python
    db = Database("app.duckdb")            # or Database() for in-memory, Database(connection=con)

    @db.register                            # CREATE TABLE IF NOT EXISTS, right away
    class User(Model, table="users"):
        id: Column[int] = column(primary_key=True)
        name: Column[str]

    db.insert(User).values(User(id=1, name="alice")).execute()
    with db.appender(User) as app:          # bulk load
        app.extend(users)
    db.select(User.name).from_(User).where(User.id == 1).fetchall()
    db.execute(create_view("v", select(...)))
    ```

    Extensions are installed and loaded on demand (spatial functions/types, functions DuckDB reports as living in an
    extension); pass `auto_install=False` to disable that, or `extensions=[...]` to load some up front.
    """

    def __init__(
        self,
        path: PathLike = ":memory:",
        *,
        read_only: bool = False,
        config: dict[str, Any] | None = None,
        extensions: Iterable[str] = (),
        auto_install: bool = True,
        connection: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        self.connection = (
            connection if connection is not None else duckdb.connect(path_str(path), read_only, config or {})
        )
        self.auto_install = auto_install
        ensure_extensions(self.connection, extensions)

    # region execution
    def execute(self, statement: Node | Query | Template) -> duckdb.DuckDBPyConnection:
        """Run a statement (or a `Query`, or a raw t-string whose values are bound as parameters)."""
        if isinstance(statement, Template):
            statement = RawSQL(statement)
        if isinstance(statement, Query):
            return statement.execute(self.connection, auto_install=self.auto_install)
        return statement.execute_on(self.connection, auto_install=self.auto_install)

    def sql(self, template: Template) -> duckdb.DuckDBPyConnection:
        """Run raw SQL from a t-string: `db.sql(t"SELECT * FROM users WHERE id = {user_id}")`."""
        return self.execute(template)

    def fetch_as[R](self, statement: Node, into: type[R]) -> list[R]:
        from parrotlet.result import rows_into

        return rows_into(self.execute(statement), into)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # endregion

    # region binding
    def bind[S: BoundStatement](self, statement: S) -> S:
        """Attach a statement built elsewhere to this database, so `.execute()` / `.fetch_as()` run here."""
        return statement._replace(_db=self)

    def select(self, *columns: ColumnInput) -> Select:
        return self.bind(select(*columns))

    def from_(self, *items: FromInput) -> Select:
        return self.bind(from_(*items))

    def insert(self, table: TableLike, columns: Sequence[str] = ()) -> Insert:
        return self.bind(insert(table, columns))

    def update(self, table: TableLike) -> Update:
        return self.bind(update(table))

    def delete(self, table: TableLike) -> Delete:
        return self.bind(delete(table))

    def merge_into(self, table: TableLike) -> Merge:
        return self.bind(merge_into(table))

    def pivot(self, source: FromInput | Statement) -> Pivot:
        return self.bind(pivot(source))

    def unpivot(self, source: FromInput | Statement) -> Unpivot:
        return self.bind(unpivot(source))

    def create_table(self, table: TableLike) -> CreateTable:
        return self.bind(create_table(table))

    def truncate(self, table: TableLike) -> SimpleStatement:
        return self.bind(truncate(table))

    # endregion

    # region models / bulk loading
    def register[M: Model](self, model: type[M]) -> type[M]:
        """Class decorator: create the model's table if it does not exist (`CREATE TABLE IF NOT EXISTS`)."""
        self.execute(create_table(model).if_not_exists())
        return model

    @overload
    def appender[M: Model](
        self,
        table: type[M],
        *,
        columns: Sequence[ColumnName] | None = None,
        action: AppendAction = "insert",
        key: Sequence[ColumnName] | None = None,
        batch_size: int | None = None,
    ) -> Appender[M]: ...
    @overload
    def appender(
        self,
        table: Table | str,
        *,
        columns: Sequence[ColumnName] | None = None,
        action: AppendAction = "insert",
        key: Sequence[ColumnName] | None = None,
        batch_size: int | None = None,
    ) -> Appender[Any]: ...
    def appender(
        self,
        table: TableLike,
        *,
        columns: Sequence[ColumnName] | None = None,
        action: AppendAction = "insert",
        key: Sequence[ColumnName] | None = None,
        batch_size: int | None = None,
    ) -> Appender[Any]:
        """DuckDB's appender for fast bulk `insert` / `upsert` / `update` / `delete`; see `Appender`."""
        return Appender(self.connection, table, columns=columns, action=action, key=key, batch_size=batch_size)

    # endregion
