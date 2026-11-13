"""DuckDB `COPY ... TO` / `COPY ... FROM` / `COPY FROM DATABASE`."""

from __future__ import annotations

from collections.abc import Sequence

from parrotlet.expr import ColumnRef
from parrotlet.query import Query, concat, quote_ident, render_literal
from parrotlet.source import TableLike, to_table
from parrotlet.statement.base import OptionValue, SimpleStatement, Statement, column_name, render_options


def copy_to(source: TableLike | Statement, path: str, **options: OptionValue) -> SimpleStatement:
    """`COPY table|(query) TO 'path' (OPTIONS)`.

    Options are DuckDB's COPY options in any case: `format="parquet"`, `header=True`, `delimiter="|"`,
    `compression="zstd"`, `partition_by=["year", "month"]`, `overwrite_or_ignore=True`, `per_thread_output=True`, ...
    """
    src = concat("(", source, ")") if isinstance(source, Statement) else to_table(source).ref()
    return SimpleStatement((Query("COPY "), src, Query(f" TO {render_literal(path)}"), render_options(options)))


def copy_from(
    table: TableLike,
    path: str,
    columns: Sequence[str | ColumnRef[object]] = (),
    **options: OptionValue,
) -> SimpleStatement:
    """`COPY table [(cols)] FROM 'path' (OPTIONS)`: load a file into an existing table."""
    cols = Query(" (" + ", ".join(quote_ident(column_name(c)) for c in columns) + ")") if columns else None
    return SimpleStatement(
        (Query("COPY "), to_table(table).ref(), cols, Query(f" FROM {render_literal(path)}"), render_options(options)),
    )


def copy_database(source: str, target: str, *, schema_only: bool = False, data_only: bool = False) -> SimpleStatement:
    """`COPY FROM DATABASE source TO target [(SCHEMA|DATA)]`: copy every object between attached databases."""
    if schema_only and data_only:
        raise ValueError("schema_only and data_only are mutually exclusive")
    mode = " (SCHEMA)" if schema_only else " (DATA)" if data_only else ""
    return SimpleStatement((Query(f"COPY FROM DATABASE {quote_ident(source)} TO {quote_ident(target)}{mode}"),))
