"""Things that can appear in FROM: tables, subqueries, CTEs, table functions, VALUES, files, samples."""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Unpack, overload, override

from parrotlet.expr import Aliased, ColumnRef, Expr, PyScalar, Star, StarModifiers, make_star, to_expr
from parrotlet.query import (
    Node,
    PathLike,
    Query,
    concat,
    ident_list,
    join,
    path_str,
    qualified,
    quote_ident,
    render_literal,
)

if TYPE_CHECKING:
    from parrotlet.model import Model

type SampleMethod = Literal["reservoir", "bernoulli", "system"]


# region Source base class


def _alias_sql(alias: str | None, columns: tuple[str, ...]) -> str:
    """` AS "alias"("c1", "c2")`"""
    if alias is None:
        if columns:
            raise ValueError("Column aliases need a table alias")
        return ""
    cols = ident_list(columns) if columns else ""
    return f" AS {quote_ident(alias)}{cols}"


class ColumnAccessor:
    """`t.c.name` → column `name` qualified by `t`."""

    __slots__ = ("_source",)

    def __init__(self, source: Source) -> None:
        self._source = source

    def __getattr__(self, name: str) -> ColumnRef[Any]:
        if name.startswith("__"):
            raise AttributeError(name)
        return self._source.col(name)

    def __getitem__(self, name: str) -> ColumnRef[Any]:
        return self._source.col(name)


class Source(Node):
    """A relation whose columns can be referenced."""

    __slots__ = ()

    @abstractmethod
    def qualifier(self) -> tuple[str, ...]: ...

    @property
    def c(self) -> ColumnAccessor:
        return ColumnAccessor(self)

    def col(self, name: str) -> ColumnRef[Any]:
        return ColumnRef(name, self.qualifier())

    def __getitem__(self, name: str) -> ColumnRef[Any]:
        return self.col(name)

    def star(self, **modifiers: Unpack[StarModifiers]) -> Star:
        """`t.*` with the same modifiers as `parrotlet.star()`."""
        return make_star(self.qualifier(), **modifiers)

    def tablesample(
        self,
        *,
        percent: float | None = None,
        rows: int | None = None,
        method: SampleMethod | None = None,
        seed: int | None = None,
    ) -> SampledSource:
        """`... TABLESAMPLE 10 PERCENT` / `TABLESAMPLE reservoir(100 ROWS) REPEATABLE (seed)`."""
        return SampledSource(self, Sample.of(percent, rows, method, seed, kind="TABLESAMPLE"))


# endregion


# region Sampling


@dataclass(frozen=True, slots=True, eq=False)
class Sample(Node):
    """`USING SAMPLE ...` (after WHERE) or `TABLESAMPLE ...` (on a FROM item)."""

    size: float
    unit: Literal["%", "ROWS"]
    method: SampleMethod | None = None
    seed: int | None = None
    kind: Literal["USING SAMPLE", "TABLESAMPLE"] = "USING SAMPLE"

    @staticmethod
    def of(
        percent: float | None,
        rows: int | None,
        method: SampleMethod | None,
        seed: int | None,
        *,
        kind: Literal["USING SAMPLE", "TABLESAMPLE"],
    ) -> Sample:
        if (percent is None) == (rows is None):
            raise ValueError("Specify exactly one of percent= or rows=")
        if percent is not None:
            return Sample(float(percent), "%", method, seed, kind)
        return Sample(int(rows or 0), "ROWS", method, seed, kind)

    @override
    def build(self) -> Query:
        size = f"{self.size:g} PERCENT" if self.unit == "%" else f"{int(self.size)} ROWS"
        if self.kind == "USING SAMPLE":
            tail = ""
            if self.method is not None or self.seed is not None:
                parts = [p for p in (self.method, str(int(self.seed)) if self.seed is not None else None) if p]
                tail = " (" + ", ".join(parts) + ")"
            return Query(f" USING SAMPLE {size}{tail}")
        body = f"{self.method}({size})" if self.method is not None else size
        seed = f" REPEATABLE ({int(self.seed)})" if self.seed is not None else ""
        return Query(f" TABLESAMPLE {body}{seed}")


@dataclass(frozen=True, slots=True, eq=False)
class SampledSource(Source):
    source: Source
    sample: Sample

    @override
    def qualifier(self) -> tuple[str, ...]:
        return self.source.qualifier()

    @override
    def build(self) -> Query:
        return concat(self.source, self.sample)


# endregion


# region FROM sources


@dataclass(frozen=True, slots=True, eq=False)
class Table(Source):
    name: str
    schema: str | None = None
    catalog: str | None = None
    alias: str | None = None
    columns: tuple[str, ...] = ()

    @override
    def qualifier(self) -> tuple[str, ...]:
        if self.alias is not None:
            return (self.alias,)
        return tuple(n for n in (self.catalog, self.schema, self.name) if n is not None)

    def as_(self, alias: str, columns: Sequence[str] = ()) -> Table:
        """`t AS alias` or, with `columns`, `t AS alias(c1, c2, ...)` (renames the columns positionally)."""
        return Table(self.name, self.schema, self.catalog, alias, tuple(columns))

    def ref(self) -> Query:
        """The table name without alias."""
        return Query(qualified(self.catalog, self.schema, self.name))

    @override
    def build(self) -> Query:
        return self.ref() + Query(_alias_sql(self.alias, self.columns))


@dataclass(frozen=True, slots=True, eq=False)
class SubqueryRef(Source):
    """`(SELECT ...) AS alias[(columns)]`"""

    query: Node
    alias: str
    lateral: bool = False
    columns: tuple[str, ...] = ()

    @override
    def qualifier(self) -> tuple[str, ...]:
        return (self.alias,)

    @override
    def build(self) -> Query:
        return concat(
            "LATERAL (" if self.lateral else "(",
            self.query,
            Query(")" + _alias_sql(self.alias, self.columns)),
        )


@dataclass(frozen=True, slots=True, eq=False)
class CTE(Source):
    """A named common table expression. Use it in `.with_()` and then as a table in FROM/JOIN."""

    name: str
    query: Node
    columns: tuple[str, ...] = ()
    materialized: bool | None = None
    using_key: tuple[str, ...] = ()

    @override
    def qualifier(self) -> tuple[str, ...]:
        return (self.name,)

    @override
    def build(self) -> Query:
        return Query(quote_ident(self.name))

    def definition(self) -> Query:
        head = quote_ident(self.name)
        if self.columns:
            head += " " + ident_list(self.columns)
        if self.using_key:
            head += " USING KEY " + ident_list(self.using_key)
        mat = {None: "", True: " MATERIALIZED", False: " NOT MATERIALIZED"}[self.materialized]
        return concat(Query(f"{head} AS{mat} ("), self.query, ")")


@dataclass(frozen=True, slots=True, eq=False)
class FunctionSource(Source):
    """A table function in FROM, e.g. `read_parquet('data/*.parquet') AS t`."""

    call: Expr[Any]
    alias: str | None = None
    columns: tuple[str, ...] = ()
    ordinality: bool = False

    @override
    def qualifier(self) -> tuple[str, ...]:
        if self.alias is None:
            raise ValueError("Give the table function an alias (.as_()) to reference its columns")
        return (self.alias,)

    def as_(self, alias: str, columns: Sequence[str] = ()) -> FunctionSource:
        return FunctionSource(self.call, alias, tuple(columns), self.ordinality)

    def with_ordinality(self) -> FunctionSource:
        """`... WITH ORDINALITY`: adds a 1-based row number column."""
        return FunctionSource(self.call, self.alias, self.columns, True)

    @override
    def build(self) -> Query:
        return concat(
            self.call,
            " WITH ORDINALITY" if self.ordinality else None,
            Query(_alias_sql(self.alias, self.columns)),
        )


@dataclass(frozen=True, slots=True, eq=False)
class ValuesSource(Source):
    """`(VALUES (...), (...)) AS alias(columns)`"""

    rows: tuple[tuple[Expr[Any], ...], ...]
    alias: str
    columns: tuple[str, ...] = ()

    @override
    def qualifier(self) -> tuple[str, ...]:
        return (self.alias,)

    @override
    def build(self) -> Query:
        rows = join(", ", (concat("(", join(", ", r), ")") for r in self.rows))
        return concat("(VALUES ", rows, Query(")" + _alias_sql(self.alias, self.columns)))


@dataclass(frozen=True, slots=True, eq=False)
class FileSource(Source):
    """DuckDB's replacement scan: `FROM 'data/*.parquet'` (CSV, Parquet, JSON, ... detected from the path)."""

    path: str
    alias: str | None = None
    columns: tuple[str, ...] = ()

    @override
    def qualifier(self) -> tuple[str, ...]:
        if self.alias is None:
            raise ValueError("Give the file an alias (.as_()) to reference its columns")
        return (self.alias,)

    def as_(self, alias: str, columns: Sequence[str] = ()) -> FileSource:
        return FileSource(self.path, alias, tuple(columns))

    @override
    def build(self) -> Query:
        # The path must be a literal here (a parameter is not a table).
        return Query(render_literal(self.path) + _alias_sql(self.alias, self.columns))


# endregion


# region Constructors


@overload
def table(name: str, *, schema: str | None = None, catalog: str | None = None, alias: str | None = None) -> Table: ...
@overload
def table(name: type[Model], *, alias: str | None = None) -> Table: ...
def table(
    name: str | type[Model],
    *,
    schema: str | None = None,
    catalog: str | None = None,
    alias: str | None = None,
) -> Table:
    """A table reference: by name (`table("events", schema="raw")`) or for a Model (`table(User)`).

    Use it for table-level operations: `table(User).star(exclude=["password"])`, `table(User).as_("u")`,
    `table(User).tablesample(percent=10)`, `table(User).name`.
    """
    if isinstance(name, str):
        return Table(name, schema, catalog, alias)
    found = model_table(name)
    if found is None:
        raise TypeError(f"{name!r} is not a Model")
    if schema is not None or catalog is not None:
        raise TypeError("schema / catalog come from the Model; set them with class keywords")
    return found if alias is None else found.as_(alias)


def table_function(call: Expr[Any], alias: str | None = None) -> FunctionSource:
    """Use any function call as a FROM source: `table_function(func.my_table_macro(1), "t")`."""
    return FunctionSource(call, alias)


def values(
    *rows: Sequence[Expr[Any] | PyScalar],
    alias: str = "values",
    columns: Sequence[str] = (),
) -> ValuesSource:
    """A VALUES list as a table: `values((1, "a"), (2, "b"), alias="v", columns=["k", "s"])`."""
    if not rows:
        raise ValueError("values() needs at least one row")
    if len({len(r) for r in rows}) > 1:
        raise ValueError("All rows must have the same number of values")
    return ValuesSource(tuple(tuple(to_expr(v) for v in r) for r in rows), alias, tuple(columns))


def file(path: PathLike, alias: str | None = None, columns: Sequence[str] = ()) -> FileSource:
    """Read a file (or glob) directly: `select().from_(file("data/*.parquet"))`; `path` may be a `pathlib.Path`."""
    return FileSource(path_str(path), alias, tuple(columns))


# endregion


# region Coercion


type FromItem = Source | Aliased | Expr[Any]


def model_table(value: object) -> Table | None:
    """The `Table` of a `Model` class, or None if `value` is not a model."""
    if isinstance(value, type):
        table = getattr(value, "__table__", None)
        if isinstance(table, Table):
            return table
    return None


type TableLike = Table | str | type[Model]


def to_from_item(value: object) -> Node:
    if isinstance(value, str):
        return Table(value)
    if (table := model_table(value)) is not None:
        return table
    if isinstance(value, Expr):
        return FunctionSource(value)
    if isinstance(value, (Source, Aliased)):
        return value
    if isinstance(value, Node):
        raise TypeError("Use .subquery(alias) to put a statement in FROM")
    raise TypeError(f"Cannot use {type(value).__name__} as a FROM item")


def to_source(value: object) -> Source:
    item = to_from_item(value)
    if not isinstance(item, Source):
        raise TypeError(f"{value!r} cannot be sampled or aliased")
    return item


def tablesample(
    source: str | Source | type[Any],
    *,
    percent: float | None = None,
    rows: int | None = None,
    method: SampleMethod | None = None,
    seed: int | None = None,
) -> SampledSource:
    """`FROM t TABLESAMPLE ...` for a table name, `table()`, a Model or any other FROM source."""
    return to_source(source).tablesample(percent=percent, rows=rows, method=method, seed=seed)


def to_table(value: TableLike) -> Table:
    """Coerce a DML/DDL target. A model's alias is kept (DuckDB accepts `UPDATE t AS a`)."""
    if isinstance(value, str):
        return Table(value)
    if isinstance(value, Table):
        return value
    table = model_table(value)
    if table is None:
        raise TypeError(f"Cannot use {value!r} as a table")
    return table


# endregion
