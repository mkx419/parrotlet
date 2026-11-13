"""Convert query results into typed Python objects (dataclasses, NamedTuples, TypedDicts, annotated classes)."""

from __future__ import annotations

import types
import typing
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, cast, get_type_hints

import shapely
from shapely.geometry.base import BaseGeometry

if TYPE_CHECKING:
    import duckdb


def _geometry_type(hint: object) -> bool:
    """True if the annotation is a shapely geometry (possibly `| None`)."""
    origin = typing.get_origin(hint)
    if origin in (typing.Union, types.UnionType):
        return any(_geometry_type(a) for a in typing.get_args(hint) if a is not type(None))
    return isinstance(hint, type) and issubclass(hint, BaseGeometry)


def _converter(hint: object) -> Callable[[object], object] | None:
    if _geometry_type(hint):
        return lambda v: shapely.from_wkb(v) if isinstance(v, (bytes, bytearray, memoryview)) else v
    return None


def rows_into[R](cursor: duckdb.DuckDBPyConnection, into: type[R]) -> list[R]:
    """Build one `into(**row)` per result row, matching columns to fields by name.

    Fields annotated with a shapely geometry type receive `shapely.from_wkb(...)` of the GEOMETRY column (DuckDB returns
    geometries as WKB bytes). Columns without a matching field raise `ValueError`.
    """
    description: Sequence[Sequence[Any]] | None = cursor.description
    if description is None:
        raise ValueError("The statement returned no result set (add RETURNING to fetch from DML)")
    names = [d[0] for d in description]

    from parrotlet.model import Model

    if isinstance(into, type) and issubclass(into, Model):
        return [cast("R", into.from_row(dict(zip(names, row, strict=True)))) for row in cursor.fetchall()]

    hints = get_type_hints(into)
    unknown = [n for n in names if n not in hints]
    if unknown:
        raise ValueError(f"Columns {unknown} have no matching field on {into.__name__}; alias them with .as_()")
    converters = [_converter(hints[n]) for n in names]

    out: list[R] = []
    for row in cursor.fetchall():
        values = {
            n: (c(v) if c is not None and v is not None else v) for n, c, v in zip(names, converters, row, strict=True)
        }
        out.append(into(**values))
    return out
