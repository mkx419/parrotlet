"""DuckDB data types, for `CAST` and `Column(...)`. Each is a `DataType[T]` carrying its phantom SQL type `T`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, overload, override

from parrotlet import sqltypes as t
from parrotlet.query import Node, Query, quote_ident, render_literal


@dataclass(frozen=True, slots=True)
class DataType[T](Node):
    name: str
    extension: str | None = None
    """The DuckDB extension defining the type (installed/loaded automatically before execution)."""

    @override
    def build(self) -> Query:
        return Query(self.name, extensions=frozenset({self.extension} if self.extension else ()))

    @override
    def __str__(self) -> str:
        return self.name

    def as_list(self) -> DataType[t.List[T]]:
        """`T[]`"""
        return DataType(f"{self.name}[]", self.extension)

    def as_array(self, size: int) -> DataType[t.Array[T]]:
        """`T[size]` (fixed-size ARRAY)"""
        return DataType(f"{self.name}[{int(size)}]", self.extension)


# A type name typed as a string: letters/underscores/spaces, optional (p[, s]), optional [] / [n] suffixes.
_TYPE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_ ]*(\(\s*\d+\s*(,\s*\d+\s*)?\))?(\[\d*\])*")


@overload
def to_type[T](value: DataType[T]) -> DataType[T]: ...
@overload
def to_type(value: str) -> DataType[Any]: ...
def to_type(value: DataType[Any] | str) -> DataType[Any]:
    """Accept a `DataType` or a plain type name such as `"INTEGER"` (which is untyped: `DataType[Any]`)."""
    if isinstance(value, DataType):
        return value
    if not _TYPE_NAME.fullmatch(value.strip()):
        raise ValueError(f"Invalid type name: {value!r}. Use parrotlet.datatype helpers for complex types.")
    return DataType[Any](value.strip())


BOOLEAN = DataType[t.Boolean]("BOOLEAN")
TINYINT = DataType[t.TinyInt]("TINYINT")
SMALLINT = DataType[t.SmallInt]("SMALLINT")
INTEGER = DataType[t.Integer]("INTEGER")
BIGINT = DataType[t.BigInt]("BIGINT")
HUGEINT = DataType[t.HugeInt]("HUGEINT")
UTINYINT = DataType[t.UTinyInt]("UTINYINT")
USMALLINT = DataType[t.USmallInt]("USMALLINT")
UINTEGER = DataType[t.UInteger]("UINTEGER")
UBIGINT = DataType[t.UBigInt]("UBIGINT")
UHUGEINT = DataType[t.UHugeInt]("UHUGEINT")
FLOAT = DataType[t.Float]("FLOAT")
DOUBLE = DataType[t.Double]("DOUBLE")
VARCHAR = DataType[t.Varchar]("VARCHAR")
BLOB = DataType[t.Blob]("BLOB")
BIT = DataType[t.Bit]("BIT")
UUID = DataType[t.Uuid]("UUID")
DATE = DataType[t.Date]("DATE")
TIME = DataType[t.Time]("TIME")
TIMETZ = DataType[t.TimeTz]("TIMETZ")
TIMESTAMP = DataType[t.Timestamp]("TIMESTAMP")
TIMESTAMP_S = DataType[t.TimestampS]("TIMESTAMP_S")
TIMESTAMP_MS = DataType[t.TimestampMs]("TIMESTAMP_MS")
TIMESTAMP_NS = DataType[t.TimestampNs]("TIMESTAMP_NS")
TIMESTAMPTZ = DataType[t.TimestampTz]("TIMESTAMPTZ")
INTERVAL = DataType[t.Interval]("INTERVAL")
JSON = DataType[t.Json]("JSON")
POINT_2D = DataType[t.Point2D]("POINT_2D", "spatial")
LINESTRING_2D = DataType[t.LineString2D]("LINESTRING_2D", "spatial")
POLYGON_2D = DataType[t.Polygon2D]("POLYGON_2D", "spatial")
BOX_2D = DataType[t.Box2D]("BOX_2D", "spatial")
BOX_2DF = DataType[t.Box2DF]("BOX_2DF", "spatial")


@dataclass(frozen=True, slots=True)
class GeometryType(DataType[t.Geometry]):
    """`GEOMETRY`, or `GEOMETRY('<crs>')` when called: `GEOMETRY("OGC:CRS84")`."""

    def __call__(self, crs: str) -> DataType[t.Geometry]:
        return DataType(f"GEOMETRY({render_literal(crs)})")


GEOMETRY = GeometryType("GEOMETRY")


def DECIMAL(precision: int = 18, scale: int = 3) -> DataType[t.Decimal]:
    return DataType(f"DECIMAL({int(precision)}, {int(scale)})")


def LIST[T](element: DataType[T]) -> DataType[t.List[T]]:
    return element.as_list()


def ARRAY[T](element: DataType[T], size: int) -> DataType[t.Array[T]]:
    return element.as_array(size)


def STRUCT(**fields: DataType[Any] | str) -> DataType[t.Struct]:
    body = ", ".join(f"{quote_ident(k)} {to_type(v)}" for k, v in fields.items())
    return DataType(f"STRUCT({body})")


def MAP[K, V](key: DataType[K], value: DataType[V]) -> DataType[t.Map[K, V]]:
    return DataType(f"MAP({key}, {value})")


def UNION(**members: DataType[Any] | str) -> DataType[t.Union]:
    body = ", ".join(f"{quote_ident(k)} {to_type(v)}" for k, v in members.items())
    return DataType(f"UNION({body})")


def ENUM(*values: str) -> DataType[t.Enum]:
    return DataType(f"ENUM({', '.join(render_literal(v) for v in values)})")
