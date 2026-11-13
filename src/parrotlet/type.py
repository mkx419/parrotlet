"""DuckDB data types (`import parrotlet.type as qlt`).

Each DuckDB type is a class with a PEP 8 CapWords name, and the same class serves two purposes:

- As a value, it is the type in `CAST`, `column(...)`, `ALTER TABLE` ... A type without arguments is used as the class
  itself (`qlt.Integer`; `qlt.Integer()` is the same); a type with arguments is an instance (`qlt.Decimal(10, 2)`,
  `qlt.List(qlt.Varchar)`, `qlt.Struct(a=qlt.Integer)`).
- As the type parameter of `Expr[T]`, it describes the SQL type of an expression for static type checking
  (`Expr[qlt.Integer]`). Subclassing encodes DuckDB's implicit casts: an `Expr[Integer]` is accepted wherever an
  `Expr[BigInt]` or `Expr[Double]` is expected, an `Expr[Date]` wherever an `Expr[Timestamp]` is, and so on. An untyped
  expression is `Expr[Any]`, which is compatible with everything.

Abstract families such as `Numeric` exist only for type checking and cannot be rendered.
"""

from __future__ import annotations

import re
from typing import ClassVar, cast, overload, override

from parrotlet.query import Query, quote_ident, render_literal

__all__ = [
    "Array",
    "BigInt",
    "Bignum",
    "Bit",
    "Blob",
    "Boolean",
    "Box2D",
    "Box2DF",
    "Date",
    "Decimal",
    "Double",
    "Enum",
    "Float",
    "Geometry",
    "HugeInt",
    "Integer",
    "Interval",
    "Json",
    "LineString2D",
    "List",
    "Map",
    "Numeric",
    "Point2D",
    "Polygon2D",
    "SmallInt",
    "SqlType",
    "Struct",
    "Time",
    "TimeNs",
    "TimeTz",
    "Timestamp",
    "TimestampMs",
    "TimestampNs",
    "TimestampS",
    "TimestampTz",
    "TimestampTzNs",
    "TinyInt",
    "TypeLike",
    "UBigInt",
    "UHugeInt",
    "UInteger",
    "USmallInt",
    "UTinyInt",
    "Union",
    "Uuid",
    "Varchar",
    "Variant",
    "to_type",
]

# region Base class


class SqlType:
    """Base of all DuckDB types. Subclasses set `sql_name` (and `sql_extension` for extension types)."""

    __slots__ = ("_extension", "_sql")
    sql_name: ClassVar[str | None] = None
    """The DuckDB type name; `None` for abstract families that only exist for type checking."""
    sql_extension: ClassVar[str | None] = None
    """The DuckDB extension defining the type (installed/loaded automatically before execution)."""

    def __init__(self) -> None:
        if self.sql_name is None:
            raise TypeError(f"{type(self).__name__} is an abstract type family, not a DuckDB type")
        self._set(self.sql_name, self.sql_extension)

    def _set(self, sql: str, extension: str | None = None) -> None:
        self._sql = sql
        self._extension = extension

    @property
    def sql(self) -> str:
        """The type as DuckDB SQL, e.g. `DECIMAL(10, 2)` or `VARCHAR[]`."""
        return self._sql

    @property
    def extension(self) -> str | None:
        return self._extension

    def build(self) -> Query:
        """The type as a SQL fragment that also records the extension it needs."""
        return Query(self._sql, extensions=frozenset({self._extension} if self._extension else ()))

    @override
    def __str__(self) -> str:
        return self._sql

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}<{self._sql}>"

    @override
    def __eq__(self, other: object) -> bool:
        return isinstance(other, SqlType) and type(other) is type(self) and other._sql == self._sql

    @override
    def __hash__(self) -> int:
        return hash((type(self), self._sql))


type TypeLike = type[SqlType] | SqlType | str
"""A DuckDB type: a class (`qlt.Integer`), an instance (`qlt.Decimal(10, 2)`) or a type name (`"INTEGER"`)."""

# A type name typed as a string: letters/underscores/spaces, optional (p[, s]), optional [] / [n] suffixes.
_TYPE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_ ]*(\(\s*\d+\s*(,\s*\d+\s*)?\))?(\[\d*\])*")


class _Named(SqlType):
    """A type given by name (`"INTEGER"`); untyped for the type checker."""

    __slots__ = ()

    def __init__(self, name: str) -> None:
        self._set(name)


@overload
def to_type[T: SqlType](value: type[T] | T) -> T: ...
@overload
def to_type(value: str) -> SqlType: ...
def to_type(value: TypeLike) -> SqlType:
    """A type instance from a class, an instance or a plain type name such as `"INTEGER"`."""
    if isinstance(value, SqlType):
        return value
    if isinstance(value, type):
        try:
            return value()
        except TypeError as error:
            if value.sql_name is None:
                raise
            raise TypeError(f"{value.__name__} takes arguments; write {value.__name__}(...)") from error
    if not _TYPE_NAME.fullmatch(value.strip()):
        raise ValueError(f"Invalid type name: {value!r}. Use the parrotlet.type classes for complex types.")
    return _Named(value.strip())


def _type_of(value: object) -> SqlType:
    """`to_type()` for the element types of the generic classes (`List[T]` ...), whose `T` is not bound to SqlType."""
    return to_type(cast("TypeLike", value))


def _type_sql(value: TypeLike) -> str:
    return to_type(value).sql


def _members(members: dict[str, TypeLike]) -> str:
    """`"a" INTEGER, "b" VARCHAR` for STRUCT / UNION."""
    return ", ".join(f"{quote_ident(k)} {_type_sql(v)}" for k, v in members.items())


# endregion


# region Boolean and numbers
# Narrower types subclass the types they implicitly cast to: TINYINT -> SMALLINT -> INTEGER -> BIGINT -> HUGEINT ->
# DECIMAL -> DOUBLE, FLOAT -> DOUBLE, and unsigned types to both their wider unsigned and signed counterparts.


class Boolean(SqlType):
    __slots__ = ()
    sql_name = "BOOLEAN"


class Numeric(SqlType):
    """Any number (abstract)."""

    __slots__ = ()


class Double(Numeric):
    __slots__ = ()
    sql_name = "DOUBLE"


class Float(Double):
    __slots__ = ()
    sql_name = "FLOAT"


class Decimal(Double):
    """`DECIMAL(precision, scale)`; `Decimal` / `Decimal()` is `DECIMAL(18, 3)`."""

    __slots__ = ()
    sql_name = "DECIMAL"

    def __init__(self, precision: int = 18, scale: int = 3) -> None:
        self._set(f"DECIMAL({int(precision)}, {int(scale)})")


class HugeInt(Decimal):
    __slots__ = ()
    sql_name = "HUGEINT"

    def __init__(self) -> None:  # integers take no arguments, unlike DECIMAL
        SqlType.__init__(self)


class UHugeInt(Decimal):
    __slots__ = ()
    sql_name = "UHUGEINT"

    def __init__(self) -> None:
        SqlType.__init__(self)


class BigInt(HugeInt):
    __slots__ = ()
    sql_name = "BIGINT"


class UBigInt(UHugeInt, HugeInt):
    __slots__ = ()
    sql_name = "UBIGINT"


class Integer(BigInt):
    __slots__ = ()
    sql_name = "INTEGER"


class UInteger(UBigInt, BigInt):
    __slots__ = ()
    sql_name = "UINTEGER"


class SmallInt(Integer):
    __slots__ = ()
    sql_name = "SMALLINT"


class USmallInt(UInteger, Integer):
    __slots__ = ()
    sql_name = "USMALLINT"


class TinyInt(SmallInt):
    __slots__ = ()
    sql_name = "TINYINT"


class UTinyInt(USmallInt, SmallInt):
    __slots__ = ()
    sql_name = "UTINYINT"


class Bignum(Numeric):
    __slots__ = ()
    sql_name = "BIGNUM"


# endregion


# region Strings and binary


class Varchar(SqlType):
    __slots__ = ()
    sql_name = "VARCHAR"


class Json(Varchar):
    __slots__ = ()
    sql_name = "JSON"


class Enum(Varchar):
    """`ENUM('a', 'b', ...)`"""

    __slots__ = ()
    sql_name = "ENUM"

    def __init__(self, *values: str) -> None:
        if not values:
            raise TypeError("Enum needs at least one value: Enum('a', 'b')")
        self._set(f"ENUM({', '.join(render_literal(v) for v in values)})")


class Blob(SqlType):
    __slots__ = ()
    sql_name = "BLOB"


class Bit(SqlType):
    __slots__ = ()
    sql_name = "BIT"


class Uuid(SqlType):
    __slots__ = ()
    sql_name = "UUID"


# endregion


# region Date and time
# DATE -> TIMESTAMP -> TIMESTAMPTZ


class TimestampTz(SqlType):
    __slots__ = ()
    sql_name = "TIMESTAMPTZ"


class Timestamp(TimestampTz):
    __slots__ = ()
    sql_name = "TIMESTAMP"


class Date(Timestamp):
    __slots__ = ()
    sql_name = "DATE"


class TimestampS(Timestamp):
    __slots__ = ()
    sql_name = "TIMESTAMP_S"


class TimestampMs(Timestamp):
    __slots__ = ()
    sql_name = "TIMESTAMP_MS"


class TimestampNs(Timestamp):
    __slots__ = ()
    sql_name = "TIMESTAMP_NS"


class TimestampTzNs(TimestampTz):
    __slots__ = ()
    sql_name = "TIMESTAMPTZ_NS"


class TimeTz(SqlType):
    __slots__ = ()
    sql_name = "TIMETZ"


class Time(TimeTz):
    __slots__ = ()
    sql_name = "TIME"


class TimeNs(Time):
    __slots__ = ()
    sql_name = "TIME_NS"


class Interval(SqlType):
    __slots__ = ()
    sql_name = "INTERVAL"


# endregion


# region Geometry


class Geometry(SqlType):
    """DuckDB's core GEOMETRY type; `Geometry("OGC:CRS84")` sets a coordinate reference system."""

    __slots__ = ()
    sql_name = "GEOMETRY"

    def __init__(self, crs: str | None = None) -> None:
        self._set("GEOMETRY" if crs is None else f"GEOMETRY({render_literal(crs)})")


class Point2D(SqlType):
    """spatial extension POINT_2D."""

    __slots__ = ()
    sql_name = "POINT_2D"
    sql_extension = "spatial"


class LineString2D(SqlType):
    """spatial extension LINESTRING_2D."""

    __slots__ = ()
    sql_name = "LINESTRING_2D"
    sql_extension = "spatial"


class Polygon2D(SqlType):
    """spatial extension POLYGON_2D."""

    __slots__ = ()
    sql_name = "POLYGON_2D"
    sql_extension = "spatial"


class Box2D(SqlType):
    """spatial extension BOX_2D."""

    __slots__ = ()
    sql_name = "BOX_2D"
    sql_extension = "spatial"


class Box2DF(SqlType):
    """spatial extension BOX_2DF."""

    __slots__ = ()
    sql_name = "BOX_2DF"
    sql_extension = "spatial"


# endregion


# region Nested types


class List[T](SqlType):
    """`T[]`: `List(qlt.Varchar)` is `VARCHAR[]`."""

    __slots__ = ()
    sql_name = "LIST"

    # Separate overloads (not `type[T] | T`): checkers then infer `T` as `Varchar`, not `Varchar | type[Varchar]`.
    @overload
    def __init__(self, element: type[T]) -> None: ...
    @overload
    def __init__(self, element: T) -> None: ...
    def __init__(self, element: object) -> None:
        inner = _type_of(element)
        self._set(f"{inner.sql}[]", inner.extension)


class Array[T](List[T]):
    """Fixed-size `T[n]`: `Array(qlt.Double, 3)` is `DOUBLE[3]`. Implicitly casts to `T[]`."""

    __slots__ = ()
    sql_name = "ARRAY"

    @overload
    def __init__(self, element: type[T], size: int) -> None: ...
    @overload
    def __init__(self, element: T, size: int) -> None: ...
    def __init__(self, element: object, size: int) -> None:
        inner = _type_of(element)
        self._set(f"{inner.sql}[{int(size)}]", inner.extension)


class Map[K, V](SqlType):
    """`MAP(key, value)`: `Map(qlt.Varchar, qlt.Integer)`."""

    __slots__ = ()
    sql_name = "MAP"

    @overload
    def __init__(self, key: type[K], value: type[V]) -> None: ...
    @overload
    def __init__(self, key: type[K], value: V) -> None: ...
    @overload
    def __init__(self, key: K, value: type[V]) -> None: ...
    @overload
    def __init__(self, key: K, value: V) -> None: ...
    def __init__(self, key: object, value: object) -> None:
        k = _type_of(key)
        v = _type_of(value)
        self._set(f"MAP({k.sql}, {v.sql})", k.extension or v.extension)


class Struct(SqlType):
    """`STRUCT("a" INTEGER, ...)` from keyword arguments: `Struct(a=qlt.Integer, b="VARCHAR")`."""

    __slots__ = ()
    sql_name = "STRUCT"

    def __init__(self, **fields: TypeLike) -> None:
        self._set(f"STRUCT({_members(fields)})")


class Union(SqlType):
    """`UNION("a" INTEGER, ...)` from keyword arguments."""

    __slots__ = ()
    sql_name = "UNION"

    def __init__(self, **members: TypeLike) -> None:
        self._set(f"UNION({_members(members)})")


class Variant(SqlType):
    __slots__ = ()
    sql_name = "VARIANT"


# endregion
