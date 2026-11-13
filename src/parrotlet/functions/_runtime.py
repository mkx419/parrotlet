"""Runtime helpers and type aliases shared by the generated function modules."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from parrotlet.expr import (
    AggregateFunc,
    Expr,
    Func,
    Lambda,
    PyScalar,
    WindowFunc,
    as_tuple,
    make_lambda,
    to_column,
    to_expr,
)
from parrotlet.query import Node
from parrotlet.source import FunctionSource
from parrotlet.statement.base import ColumnInput

type Value = Expr[Any] | PyScalar
type PyList = list[Any]
type PyDict = dict[Any, Any]
type OrderBy = ColumnInput | Sequence[ColumnInput] | None
type LambdaArg = Callable[..., Expr[Any]] | Lambda
type TableFunction = FunctionSource

__all__ = [
    "LambdaArg",
    "OrderBy",
    "PyDict",
    "PyList",
    "PyScalar",
    "TableFunction",
    "Value",
    "aggregate",
    "arg",
    "scalar",
    "table",
    "window",
]


def arg(value: object) -> Node:
    """Coerce a function argument: Python callables become SQL lambdas, other values become expressions."""
    if callable(value) and not isinstance(value, (Node, type)):
        return make_lambda(value)  # pyright: ignore[reportArgumentType]
    return to_expr(value)


def scalar(name: str, args: Sequence[object], extension: str | None = None) -> Func[Any]:
    return Func(name, tuple(arg(a) for a in args), extension=extension)


def aggregate(
    name: str,
    args: Sequence[object],
    distinct: bool,
    order_by: OrderBy,
    extension: str | None = None,
) -> AggregateFunc[Any]:
    return AggregateFunc(
        name,
        tuple(arg(a) for a in args),
        extension=extension,
        distinct=distinct,
        order_by=tuple(to_column(o) for o in as_tuple(order_by)),
    )


def window(
    name: str,
    args: Sequence[object],
    ignore_nulls: bool,
    order_by: OrderBy = None,
    extension: str | None = None,
) -> WindowFunc[Any]:
    return WindowFunc(
        name,
        tuple(arg(a) for a in args),
        ignore_nulls=ignore_nulls,
        order_by=tuple(to_column(o) for o in as_tuple(order_by)),
        extension=extension,
    )


def table(
    name: str,
    args: Sequence[object],
    options: dict[str, object],
    extension: str | None = None,
) -> FunctionSource:
    """A table function call for FROM; `options` are rendered as named parameters (`name := value`)."""
    named = tuple((k, to_expr(v)) for k, v in options.items() if v is not None)
    return FunctionSource(Func(name, tuple(arg(a) for a in args), named, extension))
