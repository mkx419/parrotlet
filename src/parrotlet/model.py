"""Declarative models: one class is both a table definition and a dataclass-like row type (SQLModel style).

```python
class User(Model, table="users"):
    id: Column[int] = column(primary_key=True)
    name: Column[str]
    age: Column[int | None] = column(default=None, check=lambda c: c.age >= 0)
    home: Column[BaseGeometry | None] = column(default=None)

    @classmethod
    def constraints(cls) -> Sequence[Constraint]:
        return (Unique(cls.name, cls.age),)


User.age                           # ColumnRef[BigInt] -> use it in queries: User.age > 20
u = User(id=1, name="alice")       # a row; u.age is `int | None`
db.insert(User).values(u).execute(); db.from_(User).where(User.age > 20).fetch_as(User)
```

The SQL type of each column is inferred from the annotation (`int` -> BIGINT, `str` -> VARCHAR, `float` -> DOUBLE,
`Decimal` -> DECIMAL(18, 3), `bool`, `bytes`, `UUID`, `date`, `datetime`, `time`, `timedelta`, shapely geometries ->
GEOMETRY, `list[X]` -> X[], `dict[K, V]` -> MAP(K, V)); `X | None` makes it nullable, anything else is NOT NULL. Pass an
explicit type with `column(qlt.Integer)` when the default does not fit.
"""

from __future__ import annotations

import datetime
import re
import types
import typing
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal as PyDecimal
from typing import Any, ClassVar, Self, cast, dataclass_transform, overload, override
from uuid import UUID

from shapely.geometry.base import BaseGeometry

import parrotlet.type as qlt
from parrotlet import type as t
from parrotlet.expr import DEFAULT, ColumnRef, Expr, PyScalar, to_expr
from parrotlet.query import Node, Query, concat, ident_list, quote_ident
from parrotlet.source import Table, model_table
from parrotlet.type import SqlType, TypeLike, to_type

_MISSING: Any = object()

type ColumnLike = str | ColumnRef[Any] | Column[Any]
type RefTarget = str | ColumnRef[Any] | Column[Any] | type[Model]


def _column_names(columns: Sequence[ColumnLike]) -> str:
    """`("a", "b")` from column names, column references or `Column`s."""
    return ident_list(c if isinstance(c, str) else c.name for c in columns)


# region Python type -> SQL type

_SCALARS: tuple[tuple[type, SqlType], ...] = (
    (bool, qlt.Boolean()),  # before int: bool is a subclass of int
    (int, qlt.BigInt()),
    (float, qlt.Double()),
    (PyDecimal, qlt.Decimal(18, 3)),
    (str, qlt.Varchar()),
    (bytes, qlt.Blob()),
    (UUID, qlt.Uuid()),
    (datetime.datetime, qlt.Timestamp()),  # before date: datetime is a subclass of date
    (datetime.date, qlt.Date()),
    (datetime.time, qlt.Time()),
    (datetime.timedelta, qlt.Interval()),
    (BaseGeometry, qlt.Geometry()),
)


def _split_optional(tp: object) -> tuple[object, bool]:
    if typing.get_origin(tp) in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        nullable = len(args) != len(typing.get_args(tp))
        return (args[0] if len(args) == 1 else typing.Union[tuple(args)]), nullable
    return tp, False


def infer_type(tp: object) -> tuple[SqlType, bool]:
    """The DuckDB type and nullability for a Python annotation (without the `Column[...]` wrapper)."""
    inner, nullable = _split_optional(tp)
    origin = typing.get_origin(inner)
    if origin is list:
        (elem,) = typing.get_args(inner) or (Any,)
        return qlt.List(infer_type(elem)[0]), nullable
    if origin is dict:
        key, value = typing.get_args(inner) or (Any, Any)
        return qlt.Map(infer_type(key)[0], infer_type(value)[0]), nullable
    if isinstance(inner, type):
        for py, sql in _SCALARS:
            if issubclass(inner, py):
                return sql, nullable
    raise TypeError(f"Cannot infer a DuckDB type for {tp!r}; pass one explicitly: column(qlt.<Type>)")


# endregion


# region Column descriptor


class Column[P]:
    """A model column (`name: Column[str]`), the `Mapped[...]` of parrotlet.

    On the class it is a typed column reference for queries (`User.name` is a `ColumnRef[Varchar]`); on an instance it
    is the row's value (`user.name` is a `str`). Configure it with `column(...)`.
    """

    __slots__ = (
        "_name",
        "attr",
        "check",
        "collation",
        "default",
        "default_factory",
        "generated",
        "init",
        "nullable",
        "owner",
        "primary_key",
        "python_type",
        "references",
        "server_default",
        "sql_type",
        "unique",
    )

    def __init__(
        self,
        sql_type: TypeLike | None = None,
        *,
        name: str | None = None,
        primary_key: bool = False,
        nullable: bool | None = None,
        unique: bool = False,
        default: object = _MISSING,
        default_factory: Callable[[], object] | None = None,
        server_default: object = _MISSING,
        check: Expr[t.Boolean] | Callable[[Any], Expr[t.Boolean]] | None = None,
        references: RefTarget | None = None,
        generated: Expr[Any] | Callable[[Any], Expr[Any]] | None = None,
        collate: str | None = None,
        init: bool = True,
    ) -> None:
        self.sql_type: SqlType | None = to_type(sql_type) if sql_type is not None else None
        self._name = name
        self.attr: str | None = None
        self.primary_key = primary_key
        self.nullable = nullable
        self.unique = unique
        self.default_factory = default_factory
        if isinstance(default, Node):  # an SQL expression default is a server-side default
            server_default, default = default, _MISSING
        self.default = default
        self.server_default = server_default
        self.check = check
        self.references = references
        self.generated = generated
        self.collation = collate
        self.init = init
        self.owner: type | None = None
        self.python_type: object = Any

    def __set_name__(self, owner: type, attr: str) -> None:
        if self.owner is None:
            self.owner = owner
        self.attr = attr
        if self._name is None:
            self._name = attr

    @property
    def name(self) -> str:
        """The SQL column name."""
        if self._name is None:
            raise ValueError("Column is not attached to a class")
        return self._name

    # class access -> typed column reference; instance access -> value
    # (geometry first: shapely's base class is untyped, so some checkers would also match it against `int`)
    @overload
    def __get__[X: BaseGeometry](
        self: Column[X] | Column[X | None],
        obj: None,
        owner: type,
    ) -> ColumnRef[t.Geometry]: ...
    @overload
    def __get__[X: bool](self: Column[X] | Column[X | None], obj: None, owner: type) -> ColumnRef[t.Boolean]: ...
    @overload
    def __get__[X: int](self: Column[X] | Column[X | None], obj: None, owner: type) -> ColumnRef[t.BigInt]: ...
    @overload
    def __get__[X: float](self: Column[X] | Column[X | None], obj: None, owner: type) -> ColumnRef[t.Double]: ...
    @overload
    def __get__[X: PyDecimal](self: Column[X] | Column[X | None], obj: None, owner: type) -> ColumnRef[t.Decimal]: ...
    @overload
    def __get__[X: str](self: Column[X] | Column[X | None], obj: None, owner: type) -> ColumnRef[t.Varchar]: ...
    @overload
    def __get__[X: bytes](self: Column[X] | Column[X | None], obj: None, owner: type) -> ColumnRef[t.Blob]: ...
    @overload
    def __get__[X: UUID](self: Column[X] | Column[X | None], obj: None, owner: type) -> ColumnRef[t.Uuid]: ...
    @overload
    def __get__[X: datetime.datetime](
        self: Column[X] | Column[X | None],
        obj: None,
        owner: type,
    ) -> ColumnRef[t.Timestamp]: ...
    @overload
    def __get__[X: datetime.date](self: Column[X] | Column[X | None], obj: None, owner: type) -> ColumnRef[t.Date]: ...
    @overload
    def __get__[X: datetime.time](self: Column[X] | Column[X | None], obj: None, owner: type) -> ColumnRef[t.Time]: ...
    @overload
    def __get__[X: datetime.timedelta](
        self: Column[X] | Column[X | None],
        obj: None,
        owner: type,
    ) -> ColumnRef[t.Interval]: ...
    @overload
    def __get__(
        self: Column[list[str]] | Column[list[str] | None],
        obj: None,
        owner: type,
    ) -> ColumnRef[t.List[t.Varchar]]: ...
    @overload
    def __get__(
        self: Column[list[bool]] | Column[list[bool] | None],
        obj: None,
        owner: type,
    ) -> ColumnRef[t.List[t.Boolean]]: ...
    @overload
    def __get__(
        self: Column[list[int]] | Column[list[int] | None],
        obj: None,
        owner: type,
    ) -> ColumnRef[t.List[t.BigInt]]: ...
    @overload
    def __get__(
        self: Column[list[float]] | Column[list[float] | None],
        obj: None,
        owner: type,
    ) -> ColumnRef[t.List[t.Double]]: ...
    @overload
    def __get__(self, obj: None, owner: type) -> ColumnRef[Any]: ...
    @overload
    def __get__(self, obj: object, owner: type) -> P: ...
    def __get__(self, obj: object, owner: type) -> Any:
        if obj is None:
            table = getattr(owner, "__table__", None)
            return ColumnRef(self.name, table.qualifier() if isinstance(table, Table) else ())
        try:
            return obj.__dict__[cast("str", self.attr)]
        except KeyError:
            raise AttributeError(self.attr) from None

    def __set__(self, obj: object, value: P) -> None:
        obj.__dict__[cast("str", self.attr)] = value

    # region resolution
    def resolve(self, annotation: object) -> None:
        """Fill in the SQL type / nullability from the Python annotation."""
        self.python_type = annotation
        inner, optional = _split_optional(annotation)
        if self.sql_type is None:
            self.sql_type = infer_type(inner)[0]
        if self.nullable is None:
            self.nullable = optional

    def has_default(self) -> bool:
        return self.default is not _MISSING or self.default_factory is not None or self.has_server_default()

    def has_server_default(self) -> bool:
        """True if the database fills the column in (an SQL expression default)."""
        return self.server_default is not _MISSING

    def initial_value(self) -> object:
        if self.default is not _MISSING:
            return self.default
        if self.default_factory is not None:
            return self.default_factory()
        if self.has_server_default():
            return DEFAULT  # let the database fill it in on INSERT
        raise TypeError(f"missing value for {self.attr!r}")

    def _expr(self, value: object) -> Expr[Any]:
        if callable(value) and not isinstance(value, Node):
            return to_expr(value(self.owner))
        return to_expr(value)

    def definition(self) -> Query:
        """The column definition for CREATE TABLE."""
        if self.sql_type is None:
            raise ValueError(f"Column {self.name!r} has no type")
        # server_default wins; a plain Python default is also used as the SQL DEFAULT (None means "no DEFAULT")
        sql_default = self.server_default if self.server_default is not _MISSING else self.default
        if sql_default is None or (callable(sql_default) and not isinstance(sql_default, Node)):
            sql_default = _MISSING
        return concat(
            Query(quote_ident(self.name) + " "),
            self.sql_type.build(),
            Query(f" COLLATE {quote_ident(self.collation)}") if self.collation is not None else None,
            " PRIMARY KEY" if self.primary_key else None,
            " NOT NULL" if self.nullable is False and not self.primary_key else None,
            " UNIQUE" if self.unique else None,
            concat(" DEFAULT ", to_expr(sql_default)) if sql_default is not _MISSING else None,
            concat(" CHECK (", self._expr(self.check), ")") if self.check is not None else None,
            _references_sql(self.references) if self.references is not None else None,
            concat(" GENERATED ALWAYS AS (", self._expr(self.generated), ") VIRTUAL")
            if self.generated is not None
            else None,
        )

    @override
    def __repr__(self) -> str:
        return f"Column({self._name!r}, {self.sql_type})"

    # endregion


def column(
    sql_type: TypeLike | None = None,
    *,
    name: str | None = None,
    primary_key: bool = False,
    nullable: bool | None = None,
    unique: bool = False,
    default: Any = _MISSING,  # noqa: ANN401
    default_factory: Callable[[], Any] | None = None,
    server_default: Expr[Any] | PyScalar = _MISSING,
    check: Expr[t.Boolean] | Callable[[Any], Expr[t.Boolean]] | None = None,
    references: RefTarget | None = None,
    generated: Expr[Any] | Callable[[Any], Expr[Any]] | None = None,
    collate: str | None = None,
    init: bool = True,
) -> Any:  # noqa: ANN401 - typed as Any so it can be assigned to any `Column[T]` annotation
    """Configure a model column (the right-hand side of `name: Column[T] = column(...)`).

    Parameters
    ----------
    sql_type : explicit DuckDB type; inferred from the annotation when omitted.
    name : SQL column name when it differs from the attribute (`type_: Column[str] = column(name="type")`).
    primary_key, unique : constraints. `nullable` overrides the nullability inferred from `X | None`.
    default : Python default for the constructor, also rendered as the SQL `DEFAULT`. An SQL expression
        (`default=fn.now()`, `default=fn.nextval("seq")`) is a database-side default: instances created without the
        value insert `DEFAULT`.
    default_factory : Python-side default factory (e.g. `list`).
    server_default : an SQL-only default (prefer `default=<expression>`, which type checkers see as optional).
    check : column `CHECK`; an expression or `lambda cls: cls.age >= 0` (evaluated once the class exists).
    references : foreign key target: `User.id`, `"users.id"`, `User`, or a column of the same class.
    generated : `GENERATED ALWAYS AS (...) VIRTUAL`; an expression or `lambda cls: cls.price * 2`.
    collate : collation name.
    init : include the column in the constructor (`init=False` columns must have a default).
    """
    return Column(
        sql_type,
        name=name,
        primary_key=primary_key,
        nullable=nullable,
        unique=unique,
        default=default,
        default_factory=default_factory,
        server_default=server_default,
        check=check,
        references=references,
        generated=generated,
        collate=collate,
        init=init,
    )


# endregion


# region Foreign keys


def _resolve_reference(target: RefTarget) -> tuple[Table, tuple[str, ...]]:
    """Resolve a foreign key target to (table, columns)."""
    if isinstance(target, Column):
        table = model_table(target.owner)
        if table is None:
            raise ValueError(f"Cannot resolve the table of column {target.name!r}")
        return Table(table.name, table.schema, table.catalog), (target.name,)
    if isinstance(target, ColumnRef):
        if not target.qualifier:
            raise ValueError("A foreign key column reference needs a table, e.g. User.id or 'users.id'")
        *prefix, name = target.qualifier
        schema = prefix[-1] if prefix else None
        catalog = prefix[-2] if len(prefix) > 1 else None
        return Table(name, schema, catalog), (target.name,)
    if isinstance(target, str):
        table_name, _, col = target.rpartition(".")
        if not table_name:
            return Table(col), ()
        return Table(table_name), (col,)
    found = model_table(target)
    if found is None:
        raise TypeError(f"Cannot use {target!r} as a foreign key target")
    return Table(found.name, found.schema, found.catalog), ()


def _references_sql(target: RefTarget) -> Query:
    table, columns = _resolve_reference(target)
    return concat(" REFERENCES ", table.ref(), Query(" " + ident_list(columns)) if columns else None)


# endregion


# region Table constraints (returned from Model.constraints)


class Constraint(Node):
    """Base class of table constraints."""

    __slots__ = ()


class _ColumnListConstraint(Constraint):
    """`<KEYWORD> (a, b)` over columns of the table."""

    __slots__ = ("columns",)
    _keyword: ClassVar[str]

    def __init__(self, *columns: ColumnLike) -> None:
        self.columns = columns

    @override
    def build(self) -> Query:
        return Query(f"{self._keyword} {_column_names(self.columns)}")


class PrimaryKey(_ColumnListConstraint):
    """Composite `PRIMARY KEY (a, b)`."""

    __slots__ = ()
    _keyword = "PRIMARY KEY"


class Unique(_ColumnListConstraint):
    """Composite `UNIQUE (a, b)`."""

    __slots__ = ()
    _keyword = "UNIQUE"


class Check(Constraint):
    """Table-level `CHECK (condition)`."""

    __slots__ = ("condition",)

    def __init__(self, condition: Expr[t.Boolean]) -> None:
        self.condition = condition

    @override
    def build(self) -> Query:
        return concat("CHECK (", self.condition, ")")


class ForeignKey(Constraint):
    """Composite `FOREIGN KEY (a, b) REFERENCES t (x, y)`.

    `references` is a table (`"t"`, `Model`) or a sequence of columns (`[T.x, T.y]`, `["t.x", "t.y"]`).
    """

    __slots__ = ("columns", "references")

    def __init__(self, columns: Sequence[ColumnLike] | ColumnLike, references: RefTarget | Sequence[RefTarget]) -> None:
        self.columns = (columns,) if isinstance(columns, (str, ColumnRef, Column)) else tuple(columns)
        self.references = references

    @override
    def build(self) -> Query:
        head = Query("FOREIGN KEY " + _column_names(self.columns))
        refs = self.references
        if isinstance(refs, (str, ColumnRef, Column, type)):
            return head + _references_sql(cast("RefTarget", refs))
        resolved = [_resolve_reference(r) for r in cast("Sequence[RefTarget]", refs)]
        if len({tbl.ref().sql for tbl, _ in resolved}) != 1:
            raise ValueError("All referenced columns must belong to the same table")
        table = resolved[0][0]
        columns = [c for _, cols in resolved for c in cols]
        return concat(head, " REFERENCES ", table.ref(), Query(" " + ident_list(columns)))


# endregion


# region Model


def _snake_case(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _annotations(cls: type) -> dict[str, object]:
    """Resolved annotations of `cls` and its bases (base first), ignoring ones that cannot be evaluated."""
    try:
        return typing.get_type_hints(cls)
    except Exception:
        out: dict[str, object] = {}
        for klass in reversed(cls.__mro__):
            out.update(getattr(klass, "__annotations__", {}))
        return out


@dataclass_transform(kw_only_default=True, field_specifiers=(column, Column))
class Model:
    """Base class of declarative models. Subclasses are tables (unless `abstract=True`) and row types.

    Class keywords: `table` (default: the class name in snake_case), `schema`, `abstract`.
    Declare columns as `name: Column[T]` (optionally `= column(...)` or `= default_value`); table constraints by
    overriding the `constraints` classmethod. Instances are created with keyword arguments and compare by value.
    """

    __table__: ClassVar[Table]
    __columns__: ClassVar[tuple[Column[Any], ...]] = ()

    def __init_subclass__(
        cls,
        *,
        table: str | None = None,
        schema: str | None = None,
        abstract: bool = False,
        _alias: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if abstract and (table is not None or schema is not None):
            raise TypeError(f"Abstract model {cls.__name__} cannot set table= or schema=")

        columns: dict[str, Column[Any]] = {}
        for attr, annotation in _annotations(cls).items():
            if attr.startswith("_") or typing.get_origin(annotation) is ClassVar or annotation is ClassVar:
                continue
            if attr == "constraints":
                raise TypeError(
                    'A column cannot be named "constraints"; use constraints_: Column[...] = column(name=...)',
                )
            column_type = annotation
            if typing.get_origin(annotation) is Column:
                (column_type,) = typing.get_args(annotation) or (Any,)
            existing = next((k.__dict__[attr] for k in cls.__mro__ if attr in k.__dict__), _MISSING)
            if isinstance(existing, Column):
                desc = cast("Column[Any]", existing)
            else:
                desc = Column(default=existing) if existing is not _MISSING else Column()
                setattr(cls, attr, desc)
                desc.__set_name__(cls, attr)
            if desc.sql_type is None or desc.python_type is Any:
                desc.resolve(column_type)
            columns[attr] = desc

        cls.__columns__ = tuple(columns.values())
        if abstract:
            return
        if not columns:
            raise TypeError(f"{cls.__name__} defines no columns")
        parent: Table | None = getattr(cls, "__table__", None)
        name = table if table is not None else parent.name if parent is not None else _snake_case(cls.__name__)
        if schema is None and parent is not None:
            schema = parent.schema
        cls.__table__ = Table(name, schema, alias=_alias)

    def __init__(self, **values: object) -> None:
        for c in type(self).__columns__:
            attr = cast("str", c.attr)
            if attr in values:
                if not c.init:
                    raise TypeError(f"{attr!r} is not an init argument")
                self.__dict__[attr] = values.pop(attr)
            else:
                try:
                    self.__dict__[attr] = c.initial_value()
                except TypeError:
                    raise TypeError(f"{type(self).__name__}() missing keyword argument {attr!r}") from None
        if values:
            raise TypeError(f"{type(self).__name__}() got unexpected keyword arguments: {', '.join(values)}")

    @classmethod
    def constraints(cls) -> Sequence[Constraint]:
        """Override to declare table constraints (`PrimaryKey` / `Unique` / `Check` / `ForeignKey`).

        Called when the table is created, after the class is fully defined, so `cls.<column>` can be used. Call
        `super().constraints()` to keep a parent model's constraints.
        """
        return ()

    # region rows
    def to_dict(self) -> dict[str, Any]:
        """`{attribute: value}` for every column."""
        return {cast("str", c.attr): self.__dict__.get(cast("str", c.attr)) for c in type(self).__columns__}

    def to_row(self) -> dict[str, Any]:
        """`{sql_column_name: value}` for INSERT."""
        return {c.name: self.__dict__.get(cast("str", c.attr)) for c in type(self).__columns__}

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Self:
        """Build an instance from `{sql_column_name: value}` (geometries are decoded from WKB)."""
        obj = cls.__new__(cls)
        by_name = {c.name: c for c in cls.__columns__}
        for key, value in row.items():
            c = by_name.get(key)
            if c is None:
                raise ValueError(f"Column {key!r} is not a field of {cls.__name__}")
            obj.__dict__[cast("str", c.attr)] = _decode(c, value)
        for c in cls.__columns__:
            obj.__dict__.setdefault(cast("str", c.attr), None)
        return obj

    @override
    def __repr__(self) -> str:
        fields = ", ".join(f"{k}={v!r}" for k, v in self.to_dict().items())
        return f"{type(self).__name__}({fields})"

    @override
    def __eq__(self, other: object) -> bool:
        return isinstance(other, Model) and type(other) is type(self) and self.to_dict() == other.to_dict()

    __hash__ = None  # type: ignore[assignment]
    # endregion


def _decode(c: Column[Any], value: object) -> object:
    if (
        isinstance(value, (bytes, bytearray, memoryview))
        and c.sql_type is not None
        and isinstance(c.sql_type, qlt.Geometry)
    ):
        import shapely

        return shapely.from_wkb(value)
    return value


def aliased[M: Model](model: type[M], alias: str) -> type[M]:
    """An alias of a model for self joins: `Boss = aliased(User, "boss")`, then `Boss.id` is `"boss"."id"`."""
    return cast(
        "type[M]",
        types.new_class(
            model.__name__,
            (model,),
            {"_alias": alias},
            lambda ns: ns.update(__module__=model.__module__),
        ),
    )


# endregion
