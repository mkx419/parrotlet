"""DDL statements besides CREATE TABLE: views, schemas, sequences, indexes, types, macros, secrets, ALTER, DROP,
COMMENT ON. Values in DDL are rendered as literals (DuckDB cannot prepare most DDL with parameters)."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from parrotlet.datatype import DataType, to_type
from parrotlet.expr import ColumnRef, Expr, to_column, to_expr
from parrotlet.query import Node, Query, concat, inline_params, join, quote_ident, render_literal, unqualified_columns
from parrotlet.source import Table, TableLike, model_table, to_table
from parrotlet.statement.base import (
    ColumnInput,
    ObjectName,
    OptionValue,
    SimpleStatement,
    Statement,
    Value,
    column_name,
    object_name,
    render_options,
)

_MISSING: Any = object()


def _create(kind: str, *, or_replace: bool = False, temporary: bool = False, if_not_exists: bool = False) -> Query:
    if or_replace and if_not_exists:
        raise ValueError("or_replace and if_not_exists cannot be combined")
    return Query(
        "CREATE "
        + ("OR REPLACE " if or_replace else "")
        + ("TEMPORARY " if temporary else "")
        + kind
        + " "
        + ("IF NOT EXISTS " if if_not_exists else ""),
    )


def _names(names: Sequence[str]) -> str:
    return "(" + ", ".join(quote_ident(n) for n in names) + ")"


# --------------------------------------------------------------------------------------------------------------------
# CREATE
# --------------------------------------------------------------------------------------------------------------------


def create_view(
    name: ObjectName,
    query: Statement,
    *,
    columns: Sequence[str] = (),
    or_replace: bool = False,
    temporary: bool = False,
    if_not_exists: bool = False,
) -> SimpleStatement:
    """`CREATE [OR REPLACE] [TEMPORARY] VIEW [IF NOT EXISTS] name [(cols)] AS query`."""
    cols = Query(" " + _names(columns)) if columns else None
    head = _create("VIEW", or_replace=or_replace, temporary=temporary, if_not_exists=if_not_exists)
    return SimpleStatement((head, object_name(name), cols, Query(" AS "), query), inline=True)


def create_schema(name: ObjectName, *, if_not_exists: bool = False, or_replace: bool = False) -> SimpleStatement:
    return SimpleStatement((_create("SCHEMA", or_replace=or_replace, if_not_exists=if_not_exists), object_name(name)))


def create_sequence(
    name: ObjectName,
    *,
    start: int | None = None,
    increment: int | None = None,
    minvalue: int | None = None,
    maxvalue: int | None = None,
    cycle: bool = False,
    or_replace: bool = False,
    temporary: bool = False,
    if_not_exists: bool = False,
) -> SimpleStatement:
    """`CREATE SEQUENCE name [START n] [INCREMENT BY n] [MINVALUE n] [MAXVALUE n] [CYCLE]`. Use with
    `F.nextval("name")` / `F.currval("name")`."""
    opts = ""
    for keyword, value in (
        ("START", start),
        ("INCREMENT BY", increment),
        ("MINVALUE", minvalue),
        ("MAXVALUE", maxvalue),
    ):
        if value is not None:
            opts += f" {keyword} {int(value)}"
    if cycle:
        opts += " CYCLE"
    head = _create("SEQUENCE", or_replace=or_replace, temporary=temporary, if_not_exists=if_not_exists)
    return SimpleStatement((head, object_name(name), Query(opts)))


def create_index(
    name: str,
    table: TableLike,
    *columns: ColumnInput,
    unique: bool = False,
    if_not_exists: bool = False,
) -> SimpleStatement:
    """`CREATE [UNIQUE] INDEX name ON table (col, (expr), ...)` (columns may be names, model columns or expressions)."""
    if not columns:
        raise ValueError("create_index needs at least one column")
    items: list[Query] = []
    with unqualified_columns(), inline_params():
        for c in columns:
            node = to_column(c)
            sql = node.build()
            items.append(sql if isinstance(node, ColumnRef) else concat("(", sql, ")"))
    head = Query("CREATE " + ("UNIQUE " if unique else "") + "INDEX " + ("IF NOT EXISTS " if if_not_exists else ""))
    return SimpleStatement(
        (head, Query(quote_ident(name) + " ON "), to_table(table).ref(), Query(" ("), join(", ", items), Query(")")),
        inline=True,
    )


def create_type(name: ObjectName, type_: DataType[Any] | str, *, or_replace: bool = False) -> SimpleStatement:
    """`CREATE TYPE name AS <type>`, e.g. `create_type("mood", dt.ENUM("sad", "happy"))`."""
    return SimpleStatement((_create("TYPE", or_replace=or_replace), object_name(name), Query(" AS "), to_type(type_)))


@dataclass(frozen=True, slots=True)
class _MacroBody:
    names: tuple[str, ...]
    defaults: tuple[tuple[str, Expr[Any]], ...]
    body: Node
    table: bool


def _macro_body(fn: Callable[..., Expr[Any] | Statement]) -> _MacroBody:
    params = inspect.signature(fn).parameters.values()
    names, defaults = [], []
    for p in params:
        if p.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            raise ValueError("Macro parameters must be plain positional parameters")
        if p.default is p.empty:
            names.append(p.name)
        else:
            defaults.append((p.name, to_expr(p.default)))
    body = fn(*(ColumnRef[Any](p.name) for p in params))
    return _MacroBody(tuple(names), tuple(defaults), body, isinstance(body, Statement))


def create_macro(
    name: ObjectName,
    *overloads: Callable[..., Expr[Any] | Statement],
    or_replace: bool = False,
    temporary: bool = False,
    if_not_exists: bool = False,
) -> SimpleStatement:
    """`CREATE MACRO` from Python lambdas; parameters become macro parameters, Python defaults become `name := value`.

    ```python
    create_macro("add", lambda a, b=1: a + b)                  # CREATE MACRO add(a, b := 1) AS (a + b)
    create_macro("first_n", lambda n: select().from_(TF.range(n)))   # a table macro (body is a statement)
    create_macro("f", lambda a: a, lambda a, b: a + b)         # overloads by arity
    ```
    """
    if not overloads:
        raise ValueError("create_macro needs a body")
    bodies = [_macro_body(fn) for fn in overloads]
    if len({b.table for b in bodies}) > 1:
        raise ValueError("Macro overloads must be all scalar or all table macros")
    parts: list[Query] = []
    with inline_params():  # DuckDB macros cannot contain parameters
        for b in bodies:
            params = [quote_ident(n) for n in b.names]
            sig = Query("(" + ", ".join(params))
            for i, (k, v) in enumerate(b.defaults):
                sig += concat(", " if params or i else "", Query(quote_ident(k) + " := "), v)
            sig += Query(") AS TABLE " if b.table else ") AS ")
            parts.append(concat(sig, b.body))
    head = _create("MACRO", or_replace=or_replace, temporary=temporary, if_not_exists=if_not_exists)
    return SimpleStatement((head, object_name(name), join(", ", parts)), inline=True)


def create_secret(
    name: str | None = None,
    *,
    type: str,  # noqa: A002
    persistent: bool = False,
    or_replace: bool = False,
    if_not_exists: bool = False,
    storage: str | None = None,
    **options: OptionValue,
) -> SimpleStatement:
    """`CREATE [PERSISTENT] SECRET [name] [IN storage] (TYPE s3, KEY_ID '...', ...)` (temporary by default)."""
    head = _create("PERSISTENT SECRET" if persistent else "SECRET", or_replace=or_replace, if_not_exists=if_not_exists)
    opts = render_options({"type": Query(type), **options})
    return SimpleStatement(
        (
            head,
            Query(quote_ident(name)) if name else None,
            Query(f" IN {quote_ident(storage)}") if storage else None,
            opts,
        ),
        inline=True,
    )


# --------------------------------------------------------------------------------------------------------------------
# DROP
# --------------------------------------------------------------------------------------------------------------------

type DropKind = Literal["TABLE", "VIEW", "SEQUENCE", "INDEX", "SCHEMA", "MACRO", "MACRO TABLE", "TYPE", "SECRET"]


def _target(name: ObjectName | TableLike) -> Query:
    if isinstance(name, Table) or model_table(name) is not None:
        return to_table(name).ref()  # pyright: ignore[reportArgumentType]
    return object_name(name)  # pyright: ignore[reportArgumentType]


def drop(
    kind: DropKind,
    name: ObjectName | TableLike,
    *,
    if_exists: bool = False,
    cascade: bool = False,
) -> SimpleStatement:
    """`DROP <kind> [IF EXISTS] name [CASCADE]`."""
    return SimpleStatement(
        (
            Query(f"DROP {kind} " + ("IF EXISTS " if if_exists else "")),
            _target(name),
            Query(" CASCADE") if cascade else None,
        ),
    )


def drop_table(name: ObjectName | TableLike, *, if_exists: bool = False, cascade: bool = False) -> SimpleStatement:
    return drop("TABLE", name, if_exists=if_exists, cascade=cascade)


def drop_view(name: ObjectName, *, if_exists: bool = False, cascade: bool = False) -> SimpleStatement:
    return drop("VIEW", name, if_exists=if_exists, cascade=cascade)


def drop_sequence(name: ObjectName, *, if_exists: bool = False, cascade: bool = False) -> SimpleStatement:
    return drop("SEQUENCE", name, if_exists=if_exists, cascade=cascade)


def drop_index(name: ObjectName, *, if_exists: bool = False) -> SimpleStatement:
    return drop("INDEX", name, if_exists=if_exists)


def drop_schema(name: ObjectName, *, if_exists: bool = False, cascade: bool = False) -> SimpleStatement:
    return drop("SCHEMA", name, if_exists=if_exists, cascade=cascade)


def drop_macro(name: ObjectName, *, if_exists: bool = False, table: bool = False) -> SimpleStatement:
    return drop("MACRO TABLE" if table else "MACRO", name, if_exists=if_exists)


def drop_type(name: ObjectName, *, if_exists: bool = False) -> SimpleStatement:
    return drop("TYPE", name, if_exists=if_exists)


def drop_secret(name: str, *, if_exists: bool = False, persistent: bool | None = None) -> SimpleStatement:
    """`DROP [PERSISTENT|TEMPORARY] SECRET [IF EXISTS] name`."""
    scope = "" if persistent is None else ("PERSISTENT " if persistent else "TEMPORARY ")
    return SimpleStatement((Query(f"DROP {scope}SECRET " + ("IF EXISTS " if if_exists else "") + quote_ident(name)),))


# --------------------------------------------------------------------------------------------------------------------
# ALTER
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AlterTable:
    """`alter_table(T).<action>(...)`: each action is one `ALTER TABLE` statement (DuckDB allows one per statement)."""

    table: TableLike

    def _stmt(self, *parts: Node | Query | None) -> SimpleStatement:
        return SimpleStatement((Query("ALTER TABLE "), to_table(self.table).ref(), *parts), inline=True)

    def add_column(
        self,
        name: str,
        type_: DataType[Any] | str,
        *,
        default: Value = _MISSING,
        if_not_exists: bool = False,
    ) -> SimpleStatement:
        head = " ADD COLUMN " + ("IF NOT EXISTS " if if_not_exists else "") + quote_ident(name) + " "
        has_default = default is not _MISSING
        return self._stmt(
            Query(head),
            to_type(type_),
            Query(" DEFAULT ") if has_default else None,
            to_expr(default) if has_default else None,
        )

    def drop_column(
        self,
        name: str | ColumnRef[Any],
        *,
        if_exists: bool = False,
        cascade: bool = False,
    ) -> SimpleStatement:
        sql = " DROP COLUMN " + ("IF EXISTS " if if_exists else "") + quote_ident(column_name(name))
        return self._stmt(Query(sql + (" CASCADE" if cascade else "")))

    def rename_column(self, old: str | ColumnRef[Any], new: str) -> SimpleStatement:
        return self._stmt(Query(f" RENAME COLUMN {quote_ident(column_name(old))} TO {quote_ident(new)}"))

    def rename_to(self, new: str) -> SimpleStatement:
        return self._stmt(Query(f" RENAME TO {quote_ident(new)}"))

    def alter_type(
        self,
        column: str | ColumnRef[Any],
        type_: DataType[Any] | str,
        *,
        using: Expr[Any] | None = None,
    ) -> SimpleStatement:
        """`ALTER COLUMN c TYPE t [USING expr]`."""
        with unqualified_columns(), inline_params():
            using_sql = concat(" USING ", using) if using is not None else None
        return self._stmt(Query(f" ALTER COLUMN {quote_ident(column_name(column))} TYPE "), to_type(type_), using_sql)

    def set_default(self, column: str | ColumnRef[Any], value: Value) -> SimpleStatement:
        return self._stmt(Query(f" ALTER COLUMN {quote_ident(column_name(column))} SET DEFAULT "), to_expr(value))

    def drop_default(self, column: str | ColumnRef[Any]) -> SimpleStatement:
        return self._stmt(Query(f" ALTER COLUMN {quote_ident(column_name(column))} DROP DEFAULT"))

    def set_not_null(self, column: str | ColumnRef[Any]) -> SimpleStatement:
        return self._stmt(Query(f" ALTER COLUMN {quote_ident(column_name(column))} SET NOT NULL"))

    def drop_not_null(self, column: str | ColumnRef[Any]) -> SimpleStatement:
        return self._stmt(Query(f" ALTER COLUMN {quote_ident(column_name(column))} DROP NOT NULL"))

    def add_primary_key(self, *columns: str | ColumnRef[Any]) -> SimpleStatement:
        return self._stmt(Query(" ADD PRIMARY KEY " + _names([column_name(c) for c in columns])))


def alter_table(table: TableLike) -> AlterTable:
    return AlterTable(table)


def alter_view_rename(name: ObjectName, new: str) -> SimpleStatement:
    """`ALTER VIEW name RENAME TO new`."""
    return SimpleStatement((Query("ALTER VIEW "), object_name(name), Query(f" RENAME TO {quote_ident(new)}")))


# --------------------------------------------------------------------------------------------------------------------
# COMMENT ON
# --------------------------------------------------------------------------------------------------------------------

type CommentKind = Literal["TABLE", "VIEW", "SEQUENCE", "INDEX", "SCHEMA", "MACRO", "MACRO TABLE", "TYPE", "DATABASE"]


def comment_on(kind: CommentKind, name: ObjectName | TableLike, comment: str | None) -> SimpleStatement:
    """`COMMENT ON <kind> name IS 'text'` (`None` removes the comment)."""
    return SimpleStatement((Query(f"COMMENT ON {kind} "), _target(name), Query(f" IS {render_literal(comment)}")))


def comment_on_table(table: TableLike, comment: str | None) -> SimpleStatement:
    return SimpleStatement((Query("COMMENT ON TABLE "), to_table(table).ref(), Query(f" IS {render_literal(comment)}")))


def comment_on_column(column: ColumnRef[Any], comment: str | None) -> SimpleStatement:
    """`COMMENT ON COLUMN table.col IS 'text'` for a qualified column such as `User.name`."""
    if not column.qualifier:
        raise ValueError("comment_on_column needs a qualified column (e.g. User.name or table('t').c.x)")
    return SimpleStatement((Query("COMMENT ON COLUMN "), column.build(), Query(f" IS {render_literal(comment)}")))
