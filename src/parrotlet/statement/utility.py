"""DuckDB utility statements: DESCRIBE, SUMMARIZE, SHOW, EXPLAIN, ATTACH/DETACH/USE, SET/RESET, PRAGMA, CHECKPOINT,
VACUUM, ANALYZE, EXPORT/IMPORT DATABASE, INSTALL/LOAD, CALL and transactions."""

from __future__ import annotations

import re
from typing import Any, Literal

from parrotlet.expr import Expr, PyScalar, to_expr
from parrotlet.query import Query, concat, quote_ident, render_literal
from parrotlet.source import TableLike, to_table
from parrotlet.statement.base import ObjectName, OptionValue, SimpleStatement, Statement, object_name, render_options

_SETTING = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _setting(name: str) -> str:
    if not _SETTING.fullmatch(name):
        raise ValueError(f"Invalid setting / pragma / extension name: {name!r}")
    return name


def _target(target: TableLike | Statement) -> Query:
    return target.build() if isinstance(target, Statement) else to_table(target).ref()


# introspection --------------------------------------------------------------------------------------------------------


def describe(target: TableLike | Statement) -> SimpleStatement:
    """`DESCRIBE table` / `DESCRIBE query`: column names and types."""
    return SimpleStatement((Query("DESCRIBE "), _target(target)))


def summarize(target: TableLike | Statement) -> SimpleStatement:
    """`SUMMARIZE table` / `SUMMARIZE query`: per-column statistics."""
    return SimpleStatement((Query("SUMMARIZE "), _target(target)))


def show_tables(*, database: str | None = None, all: bool = False) -> SimpleStatement:  # noqa: A002
    """`SHOW TABLES [FROM db]` / `SHOW ALL TABLES`."""
    if all:
        return SimpleStatement((Query("SHOW ALL TABLES"),))
    return SimpleStatement((Query("SHOW TABLES" + (f" FROM {quote_ident(database)}" if database else "")),))


def show_databases() -> SimpleStatement:
    return SimpleStatement((Query("SHOW DATABASES"),))


def explain(statement: Statement, *, analyze: bool = False) -> SimpleStatement:
    """`EXPLAIN [ANALYZE] statement`."""
    return SimpleStatement((Query("EXPLAIN ANALYZE " if analyze else "EXPLAIN "), statement))


# databases ------------------------------------------------------------------------------------------------------------


def attach(
    path: str,
    alias: str | None = None,
    *,
    read_only: bool | None = None,
    type: str | None = None,  # noqa: A002
    if_not_exists: bool = False,
    or_replace: bool = False,
    **options: OptionValue,
) -> SimpleStatement:
    """`ATTACH [OR REPLACE] [IF NOT EXISTS] 'path' [AS alias] (TYPE ..., READ_ONLY, ...)`."""
    if or_replace and if_not_exists:
        raise ValueError("or_replace and if_not_exists cannot be combined")
    head = "ATTACH " + ("OR REPLACE " if or_replace else "") + ("IF NOT EXISTS " if if_not_exists else "")
    opts: dict[str, object] = {}
    if type is not None:
        opts["type"] = Query(_setting(type))
    if read_only is not None:
        opts["read_only"] = read_only
    opts.update(options)
    return SimpleStatement(
        (
            Query(head + render_literal(path)),
            Query(f" AS {quote_ident(alias)}") if alias else None,
            render_options(opts),
        ),
    )


def detach(name: str, *, if_exists: bool = False) -> SimpleStatement:
    return SimpleStatement((Query("DETACH " + ("IF EXISTS " if if_exists else "") + quote_ident(name)),))


def use(name: ObjectName) -> SimpleStatement:
    """`USE db` / `USE db.schema`."""
    return SimpleStatement((Query("USE "), object_name(name)))


def export_database(path: str, **options: OptionValue) -> SimpleStatement:
    """`EXPORT DATABASE 'dir' (FORMAT parquet, ...)`."""
    return SimpleStatement((Query(f"EXPORT DATABASE {render_literal(path)}"), render_options(options)))


def import_database(path: str) -> SimpleStatement:
    return SimpleStatement((Query(f"IMPORT DATABASE {render_literal(path)}"),))


def checkpoint(database: str | None = None, *, force: bool = False) -> SimpleStatement:
    sql = ("FORCE CHECKPOINT" if force else "CHECKPOINT") + (f" {quote_ident(database)}" if database else "")
    return SimpleStatement((Query(sql),))


def vacuum(table: TableLike | None = None, *, analyze: bool = False) -> SimpleStatement:
    head = Query("VACUUM ANALYZE" if analyze else "VACUUM")
    return SimpleStatement((head, concat(" ", to_table(table).ref()) if table is not None else None))


def analyze(table: TableLike | None = None) -> SimpleStatement:
    return SimpleStatement((Query("ANALYZE"), concat(" ", to_table(table).ref()) if table is not None else None))


# settings -------------------------------------------------------------------------------------------------------------

type Scope = Literal["global", "session", "local"]


def set_(name: str, value: PyScalar, *, scope: Scope | None = None) -> SimpleStatement:
    """`SET [GLOBAL|SESSION|LOCAL] name = value`, e.g. `set_("threads", 4)`."""
    prefix = f"{scope.upper()} " if scope else ""
    return SimpleStatement((Query(f"SET {prefix}{_setting(name)} = {render_literal(value)}"),))


def reset(name: str, *, scope: Scope | None = None) -> SimpleStatement:
    prefix = f"{scope.upper()} " if scope else ""
    return SimpleStatement((Query(f"RESET {prefix}{_setting(name)}"),))


def set_variable(name: str, value: Expr[Any] | PyScalar) -> SimpleStatement:
    """`SET VARIABLE name = value`; read it back with `F.getvariable("name")`."""
    return SimpleStatement((Query(f"SET VARIABLE {quote_ident(name)} = "), to_expr(value)), inline=True)


def reset_variable(name: str) -> SimpleStatement:
    return SimpleStatement((Query(f"RESET VARIABLE {quote_ident(name)}"),))


def pragma(name: str, *args: PyScalar, value: PyScalar = None) -> SimpleStatement:
    """`PRAGMA name`, `PRAGMA name(args...)` or `PRAGMA name = value`."""
    if args and value is not None:
        raise ValueError("Give either arguments or value=, not both")
    sql = f"PRAGMA {_setting(name)}"
    if args:
        sql += "(" + ", ".join(render_literal(a) for a in args) + ")"
    elif value is not None:
        sql += f" = {render_literal(value)}"
    return SimpleStatement((Query(sql),))


# extensions -----------------------------------------------------------------------------------------------------------


def install(extension: str, *, from_: str | None = None, force: bool = False) -> SimpleStatement:
    """`[FORCE] INSTALL ext [FROM community|'url']`."""
    sql = ("FORCE INSTALL " if force else "INSTALL ") + _setting(extension)
    if from_ is not None:
        sql += " FROM " + (from_ if _SETTING.fullmatch(from_) else render_literal(from_))
    return SimpleStatement((Query(sql),))


def load(extension: str) -> SimpleStatement:
    return SimpleStatement((Query(f"LOAD {_setting(extension)}"),))


# misc -----------------------------------------------------------------------------------------------------------------


def call(function: Expr[Any]) -> SimpleStatement:
    """`CALL table_function(...)`, e.g. `call(func.pragma_table_info("t"))`."""
    return SimpleStatement((Query("CALL "), function))


def begin() -> SimpleStatement:
    return SimpleStatement((Query("BEGIN TRANSACTION"),))


def commit() -> SimpleStatement:
    return SimpleStatement((Query("COMMIT"),))


def rollback() -> SimpleStatement:
    return SimpleStatement((Query("ROLLBACK"),))
