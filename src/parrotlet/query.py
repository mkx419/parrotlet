"""Core building blocks: the compiled `Query`, the `Node` base class, quoting and literal rendering."""

from __future__ import annotations

import datetime
import math
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from string.templatelib import Template
from typing import TYPE_CHECKING, Any, LiteralString, override
from uuid import UUID

from shapely.geometry.base import BaseGeometry

if TYPE_CHECKING:
    import duckdb


@dataclass(frozen=True, slots=True)
class Query:
    """A compiled SQL string with its positional (`?`) parameters and the DuckDB extensions it needs."""

    sql: str
    params: tuple[object, ...] = ()
    extensions: frozenset[str] = frozenset()

    def __add__(self, other: Query) -> Query:
        return Query(self.sql + other.sql, self.params + other.params, self.extensions | other.extensions)

    @override
    def __str__(self) -> str:
        return self.sql

    def execute(
        self,
        con: duckdb.DuckDBPyConnection | None = None,
        *,
        auto_install: bool = True,
    ) -> duckdb.DuckDBPyConnection:
        """Execute on `con`, or on DuckDB's default connection when omitted.

        With `auto_install`, extensions the query is known to need (e.g. spatial functions) are installed and loaded
        first, and an error saying a function "exists in the X extension" triggers one install/load and retry.
        """
        import duckdb

        target = con if con is not None else duckdb.default_connection()
        if auto_install and self.extensions:
            ensure_extensions(target, self.extensions)
        try:
            return target.execute(self.sql, list(self.params))
        except duckdb.Error as error:
            missing = _MISSING_EXTENSION.search(str(error)) if auto_install else None
            if missing is None:
                raise
            ensure_extensions(target, {missing.group(1)})
            return target.execute(self.sql, list(self.params))


_MISSING_EXTENSION = re.compile(r"exists in the (\w+) extension")


def ensure_extensions(con: duckdb.DuckDBPyConnection, names: Iterable[str]) -> None:
    """INSTALL (if needed) and LOAD each extension on `con`."""
    for name in names:
        if not re.fullmatch(r"\w+", name):
            raise ValueError(f"Invalid extension name: {name!r}")
        row = con.execute(
            "SELECT installed, loaded FROM duckdb_extensions() WHERE extension_name = ?",
            [name],
        ).fetchone()
        if row is not None and row[1]:
            continue
        if row is None or not row[0]:
            con.execute(f"INSTALL {name}")
        con.execute(f"LOAD {name}")


EMPTY = Query("")

_NO_PARAMS_ERRORS = (
    "parameters are not supported for a statement that expands into several",
    "can't be prepared",
    "Parameter expressions within macro",
)


class Node(ABC):
    """Anything that can be compiled into a `Query`."""

    __slots__ = ()

    @abstractmethod
    def build(self) -> Query: ...

    @property
    def sql(self) -> str:
        return self.build().sql

    @property
    def params(self) -> tuple[object, ...]:
        return self.build().params

    @property
    def sql_inline(self) -> str:
        """The SQL with every parameter rendered as a literal (for logging / debugging / pasting into a shell)."""
        return self.build_inline().sql

    def build_inline(self) -> Query:
        """Build with parameters rendered as literals."""
        with inline_params():
            return self.build()

    def execute(self, con: duckdb.DuckDBPyConnection | None = None) -> duckdb.DuckDBPyConnection:
        """Execute and return DuckDB's cursor.

        Runs on `con`, else on the `Database` the statement was created from (`db.select(...)`), else on DuckDB's
        default connection. Needed extensions are installed/loaded automatically.
        """
        db = getattr(self, "_db", None)
        if con is None and db is not None:
            return db.execute(self)
        return self.execute_on(con)

    def execute_on(
        self,
        con: duckdb.DuckDBPyConnection | None,
        *,
        auto_install: bool = True,
    ) -> duckdb.DuckDBPyConnection:
        """Execute with bound parameters on `con` (or the default connection).

        Some DuckDB statements cannot take parameters (e.g. a PIVOT without an IN list inside a query, which DuckDB
        expands into several statements); those are retried once with the values rendered as literals.
        """
        query = self.build()
        try:
            return query.execute(con, auto_install=auto_install)
        except Exception as error:
            if not query.params or not any(m in str(error) for m in _NO_PARAMS_ERRORS):
                raise
        return self.build_inline().execute(con, auto_install=auto_install)

    def fetchall(self, con: duckdb.DuckDBPyConnection | None = None) -> list[tuple[Any, ...]]:
        """Execute and return all rows as tuples."""
        return self.execute(con).fetchall()

    def fetchone(self, con: duckdb.DuckDBPyConnection | None = None) -> tuple[Any, ...] | None:
        """Execute and return the first row (or None)."""
        return self.execute(con).fetchone()

    def df(self, con: duckdb.DuckDBPyConnection | None = None) -> Any:  # noqa: ANN401
        """Execute and return a pandas DataFrame (requires pandas)."""
        return self.execute(con).df()

    def pl(self, con: duckdb.DuckDBPyConnection | None = None) -> Any:  # noqa: ANN401
        """Execute and return a polars DataFrame (requires polars)."""
        return getattr(self.execute(con), "pl")()  # noqa: B009

    def fetch[R](self, into: type[R], con: duckdb.DuckDBPyConnection | None = None) -> list[R]:
        """Execute and convert every row into `into` (a dataclass, NamedTuple, TypedDict or annotated class).

        Columns are matched to fields by name; shapely-annotated fields get geometries decoded from WKB.
        """
        from parrotlet.result import rows_into

        if getattr(self, "_returning", None) == ():
            raise ValueError("This statement returns no rows; add .returning(...) to fetch from INSERT/UPDATE/DELETE")
        return rows_into(self.execute(con), into)

    def fetch_one[R](self, into: type[R], con: duckdb.DuckDBPyConnection | None = None) -> R | None:
        """Like `fetch`, returning the first row or None."""
        rows = self.fetch(into, con)
        return rows[0] if rows else None


def text(sql: LiteralString) -> Query:
    """Wrap a trusted SQL keyword/fragment. Typed as `LiteralString` to discourage passing user input."""
    return Query(sql)


def join(separator: LiteralString, parts: Iterable[Node | Query]) -> Query:
    result = EMPTY
    sep = Query(separator)

    for i, part in enumerate(parts):
        if i:
            result += sep
        result += part if isinstance(part, Query) else part.build()

    return result


def concat(*parts: Node | Query | LiteralString | None) -> Query:
    """Concatenate fragments, skipping `None`. Plain strings are treated as trusted SQL text."""
    result = EMPTY

    for part in parts:
        if part is None:
            continue
        if isinstance(part, str):
            result += Query(part)
        elif isinstance(part, Query):
            result += part
        else:
            result += part.build()

    return result


# --------------------------------------------------------------------------------------------------------------------
# Identifiers
# --------------------------------------------------------------------------------------------------------------------


def quote_ident(name: str) -> str:
    """Quote an identifier with double quotes, escaping embedded quotes."""
    return '"' + name.replace('"', '""') + '"'


def qualified(*names: str | None) -> str:
    return ".".join(quote_ident(n) for n in names if n is not None)


_BARE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def function_name(name: str) -> str:
    """Render a function name bare if it is a plain identifier (keeps case-insensitive lookup), else quoted."""
    return name if _BARE_NAME.fullmatch(name) else quote_ident(name)


# --------------------------------------------------------------------------------------------------------------------
# Literals
# --------------------------------------------------------------------------------------------------------------------

_inline_params: ContextVar[bool] = ContextVar("parrotlet_inline_params", default=False)


@contextmanager
def inline_params() -> Iterator[None]:
    """Within this context, parameters are rendered as SQL literals (needed in DDL, where `?` is not allowed)."""
    token = _inline_params.set(True)
    try:
        yield
    finally:
        _inline_params.reset(token)


def is_inlining() -> bool:
    return _inline_params.get()


_unqualified_columns: ContextVar[bool] = ContextVar("parrotlet_unqualified_columns", default=False)


@contextmanager
def unqualified_columns() -> Iterator[None]:
    """Within this context, column references drop their table qualifier (for CREATE TABLE bodies)."""
    token = _unqualified_columns.set(True)
    try:
        yield
    finally:
        _unqualified_columns.reset(token)


def is_unqualified() -> bool:
    return _unqualified_columns.get()


def _quote_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _interval(value: datetime.timedelta) -> str:
    total_us = (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds
    return f"INTERVAL '{total_us} microseconds'"


def render_literal(value: object) -> str:
    """Render a Python value as a DuckDB SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return f"'{value}'::DOUBLE"
        return repr(value)
    if isinstance(value, Decimal):
        return f"{value}::DECIMAL" if value.is_finite() else f"'{value}'::DOUBLE"
    if isinstance(value, str):
        return _quote_string(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "'" + "".join(f"\\x{b:02X}" for b in bytes(value)) + "'::BLOB"
    if isinstance(value, BaseGeometry):
        return render_literal(value.wkb) + "::GEOMETRY"
    if isinstance(value, UUID):
        return f"'{value}'::UUID"
    # datetime must be checked before date (datetime is a subclass of date)
    if isinstance(value, datetime.datetime):
        return f"'{value.isoformat()}'::{'TIMESTAMP' if value.tzinfo is None else 'TIMESTAMPTZ'}"
    if isinstance(value, datetime.date):
        return f"'{value.isoformat()}'::DATE"
    if isinstance(value, datetime.time):
        return f"'{value.isoformat()}'::{'TIME' if value.tzinfo is None else 'TIMETZ'}"
    if isinstance(value, datetime.timedelta):
        return _interval(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(render_literal(v) for v in value) + "]"
    if isinstance(value, dict):
        items = []
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError(f"Struct keys must be str, got {type(k).__name__}")
            items.append(f"{_quote_string(k)}: {render_literal(v)}")
        return "{" + ", ".join(items) + "}"

    raise TypeError(f"Cannot render {type(value).__name__} as a SQL literal")


def _contains_geometry(value: object) -> bool:
    if isinstance(value, BaseGeometry):
        return True
    if isinstance(value, (list, tuple)):
        return any(_contains_geometry(v) for v in value)
    if isinstance(value, dict):
        return any(_contains_geometry(v) for v in value.values())
    return False


def param(value: object) -> Query:
    """A bound parameter, or an inline literal while `inline_params()` is active.

    shapely geometries are sent as WKB and cast to DuckDB's `GEOMETRY`. DuckDB cannot bind geometries nested in
    lists/structs, so such values are rendered inline instead.
    """
    if is_inlining():
        return Query(render_literal(value))
    if isinstance(value, BaseGeometry):
        return Query("CAST(? AS GEOMETRY)", (value.wkb,))
    if _contains_geometry(value):
        return Query(render_literal(value))
    return Query("?", (value,))


# --------------------------------------------------------------------------------------------------------------------
# t-string escape hatch
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RawSQL(Node):
    template: Template

    @override
    def build(self) -> Query:
        result = EMPTY

        for part in self.template:
            if isinstance(part, str):
                result += Query(part)
                continue

            value = part.value
            if isinstance(value, Query):
                result += value
            elif isinstance(value, Node):
                result += value.build()
            else:
                result += param(value)

        return result
