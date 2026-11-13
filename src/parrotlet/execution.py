"""Running compiled queries on DuckDB: the connection to use, extension loading and the retries.

Everything that talks to DuckDB lives here, so `Query.execute()`, `Node.execute()` and `Database.execute()` all follow
the same steps:

1. Install and load the extensions the query is known to need (`Query.extensions`).
2. Run it with bound `?` parameters.
3. On an error saying a function "exists in the X extension", load X and run it once more.
4. On an error saying the statement cannot take parameters, run it once more with the values rendered as literals.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from parrotlet.query import Node, Query

# region Extensions

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


# endregion


# region Running queries

# Errors meaning "this statement cannot take `?` parameters"; it is then retried with literals.
_NO_PARAMS_ERRORS = (
    "parameters are not supported for a statement that expands into several",
    "can't be prepared",
    "Parameter expressions within macro",
)


def run_query(
    query: Query,
    con: duckdb.DuckDBPyConnection | None = None,
    *,
    auto_install: bool = True,
) -> duckdb.DuckDBPyConnection:
    """Execute `query` on `con`, or on DuckDB's default connection when omitted (steps 1-3 above)."""
    target = con if con is not None else duckdb.default_connection()
    if auto_install and query.extensions:
        ensure_extensions(target, query.extensions)
    try:
        return target.execute(query.sql, list(query.params))
    except duckdb.Error as error:
        missing = _MISSING_EXTENSION.search(str(error)) if auto_install else None
        if missing is None:
            raise
        ensure_extensions(target, {missing.group(1)})
        return target.execute(query.sql, list(query.params))


def run_node(
    node: Node,
    con: duckdb.DuckDBPyConnection | None = None,
    *,
    auto_install: bool = True,
) -> duckdb.DuckDBPyConnection:
    """Build and execute `node` (steps 1-4 above)."""
    query = node.build()
    try:
        return run_query(query, con, auto_install=auto_install)
    except Exception as error:
        if not query.params or not any(m in str(error) for m in _NO_PARAMS_ERRORS):
            raise
    return run_query(node.build_inline(), con, auto_install=auto_install)


# endregion
