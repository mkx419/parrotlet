"""Phantom classes describing DuckDB types, used as the type parameter of `Expr[T]` / `DataType[T]`.

They exist only for static type checking and are never instantiated. Subclassing encodes DuckDB's implicit casts:
an `Expr[Integer]` is accepted wherever an `Expr[BigInt]` or `Expr[Double]` is expected, an `Expr[Date]` wherever an
`Expr[Timestamp]` is, and so on. An untyped expression is `Expr[Any]`, which is compatible with everything.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "Any",
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
    "UBigInt",
    "UHugeInt",
    "UInteger",
    "USmallInt",
    "UTinyInt",
    "Union",
    "Uuid",
    "Varchar",
    "Variant",
]


class SqlType:
    """Base of all phantom SQL types."""

    __slots__ = ()


class Boolean(SqlType):
    __slots__ = ()


# numbers -------------------------------------------------------------------------------------------------------------
# Narrower types subclass the types they implicitly cast to: TINYINT -> SMALLINT -> INTEGER -> BIGINT -> HUGEINT ->
# DECIMAL -> DOUBLE, FLOAT -> DOUBLE, and unsigned types to both their wider unsigned and signed counterparts.


class Numeric(SqlType):
    __slots__ = ()


class Double(Numeric):
    __slots__ = ()


class Float(Double):
    __slots__ = ()


class Decimal(Double):
    __slots__ = ()


class HugeInt(Decimal):
    __slots__ = ()


class UHugeInt(Decimal):
    __slots__ = ()


class BigInt(HugeInt):
    __slots__ = ()


class UBigInt(UHugeInt, HugeInt):
    __slots__ = ()


class Integer(BigInt):
    __slots__ = ()


class UInteger(UBigInt, BigInt):
    __slots__ = ()


class SmallInt(Integer):
    __slots__ = ()


class USmallInt(UInteger, Integer):
    __slots__ = ()


class TinyInt(SmallInt):
    __slots__ = ()


class UTinyInt(USmallInt, SmallInt):
    __slots__ = ()


class Bignum(Numeric):
    __slots__ = ()


# strings / binary ----------------------------------------------------------------------------------------------------


class Varchar(SqlType):
    __slots__ = ()


class Json(Varchar):
    __slots__ = ()


class Enum(Varchar):
    __slots__ = ()


class Blob(SqlType):
    __slots__ = ()


class Bit(SqlType):
    __slots__ = ()


class Uuid(SqlType):
    __slots__ = ()


# date / time ---------------------------------------------------------------------------------------------------------
# DATE -> TIMESTAMP -> TIMESTAMPTZ


class TimestampTz(SqlType):
    __slots__ = ()


class Timestamp(TimestampTz):
    __slots__ = ()


class Date(Timestamp):
    __slots__ = ()


class TimestampS(Timestamp):
    __slots__ = ()


class TimestampMs(Timestamp):
    __slots__ = ()


class TimestampNs(Timestamp):
    __slots__ = ()


class TimestampTzNs(TimestampTz):
    __slots__ = ()


class TimeTz(SqlType):
    __slots__ = ()


class Time(TimeTz):
    __slots__ = ()


class TimeNs(Time):
    __slots__ = ()


class Interval(SqlType):
    __slots__ = ()


# geometry ------------------------------------------------------------------------------------------------------------


class Geometry(SqlType):
    """DuckDB's core GEOMETRY type."""

    __slots__ = ()


class Point2D(SqlType):
    """spatial extension POINT_2D."""

    __slots__ = ()


class LineString2D(SqlType):
    """spatial extension LINESTRING_2D."""

    __slots__ = ()


class Polygon2D(SqlType):
    """spatial extension POLYGON_2D."""

    __slots__ = ()


class Box2D(SqlType):
    """spatial extension BOX_2D."""

    __slots__ = ()


class Box2DF(SqlType):
    """spatial extension BOX_2DF."""

    __slots__ = ()


# nested --------------------------------------------------------------------------------------------------------------


class List[T](SqlType):
    """`T[]`"""

    __slots__ = ()


class Array[T](List[T]):
    """Fixed-size `T[n]`; implicitly casts to `T[]`."""

    __slots__ = ()


class Map[K, V](SqlType):
    __slots__ = ()


class Struct(SqlType):
    __slots__ = ()


class Union(SqlType):
    __slots__ = ()


class Variant(SqlType):
    __slots__ = ()
