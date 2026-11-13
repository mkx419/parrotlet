"""Hand-written functions whose generic signatures the catalog cannot express.

The result type follows the argument types: `coalesce(User.age, 0)` is `Func[Integer]`, `max(Order.ts)` is
`AggregateFunc[Timestamp]`, `list_transform(xs, lambda x: x * 2)` maps `List[T]` to `List[R]`.
"""

# pyright: reportOverlappingOverload=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, overload

from parrotlet import sqltypes as t
from parrotlet.expr import AggregateFunc, Expr, Func, Star, WindowFunc
from parrotlet.functions import _runtime as rt
from parrotlet.functions._runtime import OrderBy, PyScalar, Value

_MISSING: Any = object()

__all__ = [
    "any_value",
    "apply",
    "arbitrary",
    "arg_max",
    "arg_min",
    "argmax",
    "argmin",
    "array_apply",
    "array_filter",
    "array_reduce",
    "array_transform",
    "coalesce",
    "count",
    "count_star",
    "filter",
    "first",
    "greatest",
    "if_",
    "ifnull",
    "lag",
    "last",
    "lead",
    "least",
    "list_apply",
    "list_filter",
    "list_pack",
    "list_reduce",
    "list_transform",
    "list_value",
    "max",
    "max_by",
    "min",
    "min_by",
    "mode",
    "nullif",
    "reduce",
    "struct_pack",
]


# scalar ---------------------------------------------------------------------------------------------------------------


def coalesce[T](first: Expr[T], /, *rest: Expr[T] | PyScalar) -> Func[T]:
    """The first non-NULL argument. SQL: `coalesce`"""
    return rt.scalar("coalesce", (first, *rest))


def ifnull[T](value: Expr[T], fallback: Expr[T] | PyScalar, /) -> Func[T]:
    """`value` if it is not NULL, else `fallback`. SQL: `ifnull`"""
    return rt.scalar("ifnull", (value, fallback))


def nullif[T](value: Expr[T], other: Expr[T] | PyScalar, /) -> Func[T]:
    """NULL if `value = other`, else `value`. SQL: `nullif`"""
    return rt.scalar("nullif", (value, other))


def greatest[T](first: Expr[T], /, *rest: Expr[T] | PyScalar) -> Func[T]:
    """The largest argument. SQL: `greatest`"""
    return rt.scalar("greatest", (first, *rest))


def least[T](first: Expr[T], /, *rest: Expr[T] | PyScalar) -> Func[T]:
    """The smallest argument. SQL: `least`"""
    return rt.scalar("least", (first, *rest))


@overload
def if_[T](condition: Expr[t.Boolean], then: Expr[T], otherwise: Expr[T] | PyScalar, /) -> Func[T]: ...
@overload
def if_[T](condition: Expr[t.Boolean], then: PyScalar, otherwise: Expr[T], /) -> Func[T]: ...
@overload
def if_(condition: Expr[t.Boolean], then: bool, otherwise: bool | None, /) -> Func[t.Boolean]: ...
@overload
def if_(condition: Expr[t.Boolean], then: int, otherwise: int | None, /) -> Func[t.Integer]: ...
@overload
def if_(condition: Expr[t.Boolean], then: float, otherwise: float | None, /) -> Func[t.Double]: ...
@overload
def if_(condition: Expr[t.Boolean], then: str, otherwise: str | None, /) -> Func[t.Varchar]: ...
@overload
def if_(condition: Expr[t.Boolean], then: PyScalar, otherwise: PyScalar, /) -> Func[Any]: ...
def if_(condition: Expr[t.Boolean], then: Value, otherwise: Value, /) -> Func[Any]:
    """`then` if `condition` is true, else `otherwise`. SQL: `if`"""
    return rt.scalar("if", (condition, then, otherwise))


def list_value[T](first: Expr[T], /, *rest: Expr[T] | PyScalar) -> Func[t.List[T]]:
    """A list of the arguments. SQL: `list_value`"""
    return rt.scalar("list_value", (first, *rest))


list_pack = list_value


def struct_pack(**fields: Value) -> Func[t.Struct]:
    """A struct from named values: `struct_pack(a=1, b=x)`. SQL: `struct_pack`"""
    return Func("struct_pack", (), tuple((k, rt.arg(v)) for k, v in fields.items()))  # type: ignore[misc]


# lambdas --------------------------------------------------------------------------------------------------------------


@overload
def list_transform[T, R](values: Expr[t.List[T]], fn: Callable[[Expr[T]], Expr[R]], /) -> Func[t.List[R]]: ...
@overload
def list_transform[T, R](
    values: Expr[t.List[T]],
    fn: Callable[[Expr[T], Expr[t.BigInt]], Expr[R]],
    /,
) -> Func[t.List[R]]: ...
def list_transform(values: Expr[Any], fn: Callable[..., Expr[Any]], /) -> Func[Any]:
    """Apply `fn` to every element: `list_transform(xs, lambda x: x * 2)`. A second lambda parameter is the 1-based
    index. SQL: `list_transform`"""
    return rt.scalar("list_transform", (values, fn))


list_apply = array_transform = array_apply = apply = list_transform


@overload
def list_filter[T](values: Expr[t.List[T]], fn: Callable[[Expr[T]], Expr[t.Boolean]], /) -> Func[t.List[T]]: ...
@overload
def list_filter[T](
    values: Expr[t.List[T]],
    fn: Callable[[Expr[T], Expr[t.BigInt]], Expr[t.Boolean]],
    /,
) -> Func[t.List[T]]: ...
def list_filter(values: Expr[Any], fn: Callable[..., Expr[Any]], /) -> Func[Any]:
    """Keep the elements for which `fn` is true. SQL: `list_filter`"""
    return rt.scalar("list_filter", (values, fn))


array_filter = filter = list_filter  # noqa: A001


@overload
def list_reduce[T](values: Expr[t.List[T]], fn: Callable[[Expr[T], Expr[T]], Expr[T]], /) -> Func[T]: ...
@overload
def list_reduce[T, A](
    values: Expr[t.List[T]],
    fn: Callable[[Expr[A], Expr[T]], Expr[A]],
    initial: Expr[A],
    /,
) -> Func[A]: ...
def list_reduce(values: Expr[Any], fn: Callable[..., Expr[Any]], initial: Value = _MISSING, /) -> Func[Any]:
    """Fold the list with `fn(accumulator, element)`, optionally starting from `initial`. SQL: `list_reduce`"""
    return rt.scalar("list_reduce", (values, fn) if initial is _MISSING else (values, fn, initial))


array_reduce = reduce = list_reduce


# aggregates -----------------------------------------------------------------------------------------------------------


@overload
def count(*, distinct: bool = False) -> AggregateFunc[t.BigInt]: ...
@overload
def count(value: Value, /, *, distinct: bool = False, order_by: OrderBy = None) -> AggregateFunc[t.BigInt]: ...
def count(value: Value = _MISSING, /, *, distinct: bool = False, order_by: OrderBy = None) -> AggregateFunc[t.BigInt]:
    """`count(*)` without arguments, else the number of non-NULL values. SQL: `count`"""
    if value is _MISSING:
        return AggregateFunc("count", (Star(),))
    return rt.aggregate("count", (value,), distinct, order_by)


def count_star() -> AggregateFunc[t.BigInt]:
    """`count_star()`, the same as `count(*)`. SQL: `count_star`"""
    return rt.aggregate("count_star", (), False, None)


def min[T](value: Expr[T], /, *, distinct: bool = False, order_by: OrderBy = None) -> AggregateFunc[T]:  # noqa: A001
    """The minimum value. SQL: `min`"""
    return rt.aggregate("min", (value,), distinct, order_by)


def max[T](value: Expr[T], /, *, distinct: bool = False, order_by: OrderBy = None) -> AggregateFunc[T]:  # noqa: A001
    """The maximum value. SQL: `max`"""
    return rt.aggregate("max", (value,), distinct, order_by)


def first[T](value: Expr[T], /, *, distinct: bool = False, order_by: OrderBy = None) -> AggregateFunc[T]:
    """The first value (in `order_by` order, if given). SQL: `first`"""
    return rt.aggregate("first", (value,), distinct, order_by)


def last[T](value: Expr[T], /, *, distinct: bool = False, order_by: OrderBy = None) -> AggregateFunc[T]:
    """The last value (in `order_by` order, if given). SQL: `last`"""
    return rt.aggregate("last", (value,), distinct, order_by)


def any_value[T](value: Expr[T], /, *, distinct: bool = False, order_by: OrderBy = None) -> AggregateFunc[T]:
    """Any non-NULL value. SQL: `any_value`"""
    return rt.aggregate("any_value", (value,), distinct, order_by)


def arbitrary[T](value: Expr[T], /, *, distinct: bool = False, order_by: OrderBy = None) -> AggregateFunc[T]:
    """The first value. SQL: `arbitrary`"""
    return rt.aggregate("arbitrary", (value,), distinct, order_by)


def mode[T](value: Expr[T], /, *, distinct: bool = False, order_by: OrderBy = None) -> AggregateFunc[T]:
    """The most frequent value. SQL: `mode`"""
    return rt.aggregate("mode", (value,), distinct, order_by)


@overload
def arg_min[T](value: Expr[T], by: Value, /, *, distinct: bool = False) -> AggregateFunc[T]: ...
@overload
def arg_min[T](
    value: Expr[T],
    by: Value,
    n: Expr[t.BigInt] | int,
    /,
    *,
    distinct: bool = False,
) -> AggregateFunc[t.List[T]]: ...
def arg_min(value: Value, by: Value, n: Value = _MISSING, /, *, distinct: bool = False) -> AggregateFunc[Any]:
    """`value` of the row with the minimum `by` (the `n` smallest as a list if `n` is given). SQL: `arg_min`"""
    return rt.aggregate("arg_min", (value, by) if n is _MISSING else (value, by, n), distinct, None)


@overload
def arg_max[T](value: Expr[T], by: Value, /, *, distinct: bool = False) -> AggregateFunc[T]: ...
@overload
def arg_max[T](
    value: Expr[T],
    by: Value,
    n: Expr[t.BigInt] | int,
    /,
    *,
    distinct: bool = False,
) -> AggregateFunc[t.List[T]]: ...
def arg_max(value: Value, by: Value, n: Value = _MISSING, /, *, distinct: bool = False) -> AggregateFunc[Any]:
    """`value` of the row with the maximum `by` (the `n` largest as a list if `n` is given). SQL: `arg_max`"""
    return rt.aggregate("arg_max", (value, by) if n is _MISSING else (value, by, n), distinct, None)


argmin = min_by = arg_min
argmax = max_by = arg_max


# window ---------------------------------------------------------------------------------------------------------------


def lag[T](
    value: Expr[T],
    offset: Expr[t.BigInt] | int = 1,
    default: Expr[T] | PyScalar = None,
    /,
    *,
    ignore_nulls: bool = False,
    order_by: OrderBy = None,
) -> WindowFunc[T]:
    """The value `offset` rows before the current row (or `default`). SQL: `lag`"""
    args: tuple[object, ...] = (value, offset) if default is None else (value, offset, default)
    return rt.window("lag", args, ignore_nulls, order_by)


def lead[T](
    value: Expr[T],
    offset: Expr[t.BigInt] | int = 1,
    default: Expr[T] | PyScalar = None,
    /,
    *,
    ignore_nulls: bool = False,
    order_by: OrderBy = None,
) -> WindowFunc[T]:
    """The value `offset` rows after the current row (or `default`). SQL: `lead`"""
    args: tuple[object, ...] = (value, offset) if default is None else (value, offset, default)
    return rt.window("lead", args, ignore_nulls, order_by)
