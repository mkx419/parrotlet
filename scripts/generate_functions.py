"""Generate typed function modules from DuckDB's function catalog (`duckdb_functions()`).

    uv run python scripts/generate_functions.py

Writes:
- src/parrotlet/functions/_core.py   scalar / aggregate / window / macro functions of core DuckDB and its builtin
                                      extensions (json, icu, parquet, ...)
- src/parrotlet/functions/tables.py  core table functions (read_parquet, range, ...)
- src/parrotlet/functions/spatial.py spatial extension functions (scalar / aggregate / macro / table)

Functions with hand-written generic signatures (see `functions/_generic.py`) are skipped here.
"""

from __future__ import annotations

import keyword
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from parrotlet import sqltypes  # noqa: E402

OUT = ROOT / "src" / "parrotlet" / "functions"

# Functions implemented by hand in functions/_generic.py (generic signatures the catalog cannot express).
HANDWRITTEN = {
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
    "if",
    "ifnull",
    "lag",
    "lead",
    "last",
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
}

MAX_OVERLOADS = 48

CLASS = {
    "BOOLEAN": "Boolean",
    "TINYINT": "TinyInt",
    "SMALLINT": "SmallInt",
    "INTEGER": "Integer",
    "BIGINT": "BigInt",
    "HUGEINT": "HugeInt",
    "UTINYINT": "UTinyInt",
    "USMALLINT": "USmallInt",
    "UINTEGER": "UInteger",
    "UBIGINT": "UBigInt",
    "UHUGEINT": "UHugeInt",
    "FLOAT": "Float",
    "DOUBLE": "Double",
    "DECIMAL": "Decimal",
    "BIGNUM": "Bignum",
    "VARCHAR": "Varchar",
    "JSON": "Json",
    "BLOB": "Blob",
    "BIT": "Bit",
    "UUID": "Uuid",
    "DATE": "Date",
    "TIMESTAMP": "Timestamp",
    "TIMESTAMP_S": "TimestampS",
    "TIMESTAMP_MS": "TimestampMs",
    "TIMESTAMP_NS": "TimestampNs",
    "TIMESTAMP WITH TIME ZONE": "TimestampTz",
    "TIMESTAMPTZ_NS": "TimestampTzNs",
    "TIME": "Time",
    "TIME WITH TIME ZONE": "TimeTz",
    "TIME_NS": "TimeNs",
    "INTERVAL": "Interval",
    "GEOMETRY": "Geometry",
    "POINT_2D": "Point2D",
    "LINESTRING_2D": "LineString2D",
    "POLYGON_2D": "Polygon2D",
    "BOX_2D": "Box2D",
    "BOX_2DF": "Box2DF",
    "VARIANT": "Variant",
    "UNION": "Union",
    "STRUCT": "Struct",
}

# Python values accepted for a parameter of the given SQL type (besides expressions).
LITERAL = {
    "Boolean": "bool",
    "Integer": "int",
    "BigInt": "int",
    "HugeInt": "int",
    "UBigInt": "int",
    "UHugeInt": "int",
    "Float": "int | float",
    "Double": "int | float | _PyDecimal",
    "Decimal": "int | float | _PyDecimal",
    "Varchar": "str",
    "Json": "str",
    "Blob": "bytes",
    "Uuid": "_UUID",
    "Date": "_dt.date",
    "Timestamp": "_dt.date",
    "TimestampTz": "_dt.date",
    "Time": "_dt.time",
    "TimeTz": "_dt.time",
    "Interval": "_dt.timedelta",
    "Geometry": "_Geom",
}

# Python types for named (keyword) options of table functions.
OPTION = {
    "Boolean": "bool",
    "Varchar": "str",
    "Double": "float",
    "Float": "float",
    "Decimal": "float",
}


# --------------------------------------------------------------------------------------------------------------------
# SQL type parsing
# --------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class T:
    kind: str  # cls | var | any | list | array | map | lambda
    name: str = ""
    args: tuple[T, ...] = ()


ANY = T("any")


def _split_top(s: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return parts


def parse(ty: str | None) -> T:
    if ty is None:
        return ANY
    ty = ty.strip()
    if m := re.fullmatch(r"(.+)\[(\d*|ANY)\]", ty):
        inner = parse(m.group(1))
        return T("list", args=(inner,)) if m.group(2) == "" else T("array", args=(inner,))
    if ty in ("T", "K", "V"):
        return T("var", ty)
    if ty == "LAMBDA":
        return T("lambda")
    if ty.startswith("MAP(") and ty.endswith(")"):
        k, v = _split_top(ty[4:-1])
        return T("map", args=(parse(k), parse(v)))
    if ty.startswith("STRUCT"):
        return T("cls", "Struct")
    if ty.startswith("DECIMAL"):
        return T("cls", "Decimal")
    if ty in CLASS:
        return T("cls", CLASS[ty])
    return ANY


def type_vars(node: T) -> set[str]:
    if node.kind == "var":
        return {node.name}
    out: set[str] = set()
    for a in node.args:
        out |= type_vars(a)
    return out


def phantom(node: T, allowed: set[str]) -> str:
    """The phantom type expression (inside `_E[...]`)."""
    match node.kind:
        case "cls":
            return f"_t.{node.name}"
        case "var":
            return node.name if node.name in allowed else "_Any"
        case "list":
            return f"_t.List[{phantom(node.args[0], allowed)}]"
        case "array":
            return f"_t.Array[{phantom(node.args[0], allowed)}]"
        case "map":
            return f"_t.Map[{phantom(node.args[0], allowed)}, {phantom(node.args[1], allowed)}]"
        case _:
            return "_Any"


def param_annotation(node: T, allowed: set[str]) -> str:
    match node.kind:
        case "any":
            return "_Value"
        case "lambda":
            return "_LambdaArg"
        case "var":
            return f"_E[{node.name}] | _PyScalar"
        case "cls":
            if node.name == "Json":
                return "_E[_t.Varchar] | str"
            lit = LITERAL.get(node.name)
            return f"_E[_t.{node.name}]" + (f" | {lit}" if lit else "")
        case "list" | "array":
            # a LIST implicitly casts to a fixed-size ARRAY, so array parameters also take lists
            return f"_E[_t.List[{phantom(node.args[0], allowed)}]] | _PyList"
        case "map":
            return f"_E[{phantom(node, allowed)}] | _PyDict"
        case _:
            return "_Value"


def option_annotation(node: T) -> str:
    if node.kind == "cls":
        if node.name in OPTION:
            return OPTION[node.name]
        if issubclass(getattr(sqltypes, node.name), sqltypes.HugeInt) or node.name in ("UBigInt", "UHugeInt"):
            return "int"
    if node.kind in ("list", "array"):
        return "_PyList"
    if node.kind == "map":
        return "_PyDict"
    return "_Value"


def rank(node: T) -> int:
    """Sort key: narrower types first so that overload resolution picks the most specific signature."""
    if node.kind == "cls":
        return -len(getattr(sqltypes, node.name).__mro__)
    if node.kind in ("list", "array", "map"):
        return 10
    if node.kind == "var":
        return 20
    return 100


# --------------------------------------------------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------------------------------------------------


@dataclass
class Overload:
    params: list[tuple[str, T]]
    varargs: T | None
    ret: T


@dataclass
class Function:
    sql_name: str
    py_name: str
    kind: str  # scalar | aggregate | window | table
    module: str
    description: str | None = None
    example: str | None = None
    overloads: list[Overload] = field(default_factory=list)
    alias_of: str | None = None
    extension: str | None = None


# Core ST_* functions are registered in lowercase, so their word boundaries cannot be derived from the name.
SNAKE_OVERRIDES = {
    "st_asbinary": "st_as_binary",
    "st_asgeojson": "st_as_geojson",
    "st_astext": "st_as_text",
    "st_aswkb": "st_as_wkb",
    "st_aswkt": "st_as_wkt",
    "st_geomfromgeojson": "st_geom_from_geojson",
    "st_geomfromwkb": "st_geom_from_wkb",
    "st_setcrs": "st_set_crs",
}


def snake_case(name: str) -> str:
    """`ST_AsText` -> `st_as_text`, `ST_GeomFromWKB` -> `st_geom_from_wkb`, `ST_Point2D` -> `st_point_2d`.

    Names DuckDB spells in lowercase (most core functions) are kept as they are.
    """
    if name in SNAKE_OVERRIDES:
        return SNAKE_OVERRIDES[name]
    name = name.replace("DWithin", "Dwithin")  # PostGIS spelling: ST_DWithin -> st_dwithin
    name = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name)
    name = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
    name = re.sub(r"(?<=[A-Za-z])(?=\d)", "_", name)
    return re.sub(r"_+", "_", name).lower()


def py_identifier(name: str) -> str:
    name = snake_case(name)
    return name + "_" if keyword.iskeyword(name) or keyword.issoftkeyword(name) else name


def param_name(name: str | None, index: int, used: set[str]) -> str:
    base = re.sub(r"\W", "_", (name or "").lower()).strip("_") or f"arg{index}"
    if base[0].isdigit():
        base = f"arg_{base}"
    if keyword.iskeyword(base) or keyword.issoftkeyword(base) or base in ("distinct", "order_by", "ignore_nulls"):
        base += "_"
    out, n = base, 1
    while out in used:
        n += 1
        out = f"{base}{n}"
    used.add(out)
    return out


KIND = {"scalar": "scalar", "macro": "scalar", "aggregate": "aggregate", "window": "window", "table": "table"}
KIND_PRIORITY = {"aggregate": 3, "window": 2, "scalar": 1}


def load() -> tuple[str, dict[tuple[str, str], Function]]:
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial")
    rows = con.execute(
        """
        SELECT function_name, function_type, extension_name, alias_of, description, examples,
               parameters, parameter_types, return_type, varargs
        FROM duckdb_functions()
        WHERE function_type IN ('scalar', 'aggregate', 'window', 'macro', 'table', 'table_macro')
        ORDER BY function_name, function_oid
        """,
    ).fetchall()
    version = duckdb.__version__

    functions: dict[tuple[str, str], Function] = {}
    for name, ftype, ext, alias_of, desc, examples, params, ptypes, rtype, varargs in rows:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            continue
        kind = "table" if ftype in ("table", "table_macro") else KIND[ftype]
        if kind != "table" and name.lower() in HANDWRITTEN:
            continue
        module = "spatial" if ext == "spatial" else ("tables" if kind == "table" else "_core")
        py_name = py_identifier(name)
        key = (module, py_name)
        fn = functions.get(key)
        if fn is None:
            fn = functions[key] = Function(name, py_name, kind, module, extension=ext if ext == "spatial" else None)
        elif kind != fn.kind:
            if kind == "table" or fn.kind == "table":
                key = (module, py_name + "_table")
                fn = functions.setdefault(
                    key,
                    Function(name, py_name + "_table", "table", module, extension=ext if ext == "spatial" else None),
                )
            elif KIND_PRIORITY[kind] > KIND_PRIORITY[fn.kind]:
                fn.kind = kind  # e.g. a name that is both scalar and aggregate: AggregateFunc covers both
        fn.description = fn.description or (desc.strip() if desc else None)
        fn.example = fn.example or (examples[0] if examples else None)
        if alias_of and alias_of.lower() != name.lower():
            fn.alias_of = alias_of
        ptypes = ptypes or [None] * len(params or [])
        fn.overloads.append(
            Overload(
                params=[(p, parse(pt)) for p, pt in zip(params or [], ptypes, strict=True)],
                varargs=parse(varargs) if varargs else None,
                ret=parse(rtype) if ftype not in ("macro", "table_macro") else ANY,
            ),
        )
    return version, functions


# --------------------------------------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------------------------------------

WRAPPER = {"scalar": "_F", "aggregate": "_A", "window": "_W"}


def docstring(fn: Function, indent: str = "    ") -> str:
    lines = []
    if fn.description:
        lines.append(" ".join(fn.description.split()))
    if fn.example:
        lines.append(f"Example: `{' '.join(fn.example.split())}`")
    lines.append(f"SQL: `{fn.sql_name}`")
    text = "\n\n".join(lines).replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    body = text.replace("\n", "\n" + indent)
    return f'{indent}"""{body}"""\n'


def signature(fn: Function, ov: Overload, positional: int | None = None) -> tuple[str, str, str]:
    """Return (type params, parameter list, return annotation) for one overload."""
    allowed = set()
    for _, node in ov.params:
        allowed |= type_vars(node)
    if ov.varargs is not None:
        allowed |= type_vars(ov.varargs)
    tparams = f"[{', '.join(sorted(allowed))}]" if allowed else ""

    used: set[str] = set()
    parts: list[str] = []
    params = ov.params
    if fn.kind == "table":
        pos = len(params) if positional is None else positional
        for i, (pname, node) in enumerate(params[:pos]):
            parts.append(f"{param_name(pname, i, used)}: {param_annotation(node, allowed)}")
        if parts:
            parts.append("/")
        if ov.varargs is not None:
            parts.append(f"*args: {param_annotation(ov.varargs, allowed)}")
        elif params[pos:]:
            parts.append("*")
        for i, (pname, node) in enumerate(params[pos:], start=pos):
            parts.append(f"{param_name(pname, i, used)}: {option_annotation(node)} | None = None")
        return tparams, ", ".join(parts), "_TableFunction"

    for i, (pname, node) in enumerate(params):
        parts.append(f"{param_name(pname, i, used)}: {param_annotation(node, allowed)}")
    if parts:
        parts.append("/")
    if ov.varargs is not None:
        parts.append(f"*args: {param_annotation(ov.varargs, allowed)}")
    extra = {
        "aggregate": ["distinct: bool = False", "order_by: _OrderBy = None"],
        "window": ["ignore_nulls: bool = False", "order_by: _OrderBy = None"],
        "scalar": [],
    }[fn.kind]
    if extra:
        if ov.varargs is None:
            parts.append("*")
        parts.extend(extra)
    ret_phantom = phantom(ov.ret, allowed) if ov.ret.kind != "lambda" else "_Any"
    return tparams, ", ".join(parts), f"{WRAPPER[fn.kind]}[{ret_phantom}]"


def table_positional(fn: Function) -> int | None:
    arities = {len(ov.params) for ov in fn.overloads}
    if len(arities) > 1:
        return None  # several arities (e.g. range(stop) / range(start, stop)): all positional
    (n,) = arities
    return min(n, 1)


def render_function(fn: Function) -> str:
    positional = table_positional(fn) if fn.kind == "table" else None

    def key(ov: Overload) -> tuple[int, int, tuple[int, ...]]:
        return (len(ov.params), ov.varargs is not None, tuple(rank(n) for _, n in ov.params))

    seen: dict[str, tuple[str, str, str]] = {}
    for ov in sorted(fn.overloads, key=key):
        sig = signature(fn, ov, positional)
        seen.setdefault(sig[0] + sig[1], sig)
    sigs = list(seen.values())

    impl_params = {
        "scalar": "*args: _Any",
        "aggregate": "*args: _Any, distinct: bool = False, order_by: _OrderBy = None",
        "window": "*args: _Any, ignore_nulls: bool = False, order_by: _OrderBy = None",
        "table": "*args: _Any, **options: _Any",
    }[fn.kind]
    impl_ret = "_TableFunction" if fn.kind == "table" else f"{WRAPPER[fn.kind]}[_Any]"

    if len(sigs) > MAX_OVERLOADS:
        sigs = []  # too many combinations to be useful: fall back to the untyped implementation signature

    out = []
    if len(sigs) == 1:
        tparams, params, ret = sigs[0]
        pos_names, opt_names = _call_args(params)
        items = [*pos_names, "*args"] if "*args" in params else pos_names
        args_expr = "(" + ", ".join(items) + ("," if len(items) == 1 else "") + ")"
        opts_expr = "{" + ", ".join(f'"{n}": {n}' for n in opt_names) + "}"
        out.append(f"def {fn.py_name}{tparams}({params}) -> {ret}:\n")
        out.append(docstring(fn))
        out.append(f"    return {call_expr(fn, args_expr, opts_expr)}\n")
        return "".join(out)

    for tparams, params, ret in sigs:
        out.append(f"@_overload\ndef {fn.py_name}{tparams}({params}) -> {ret}: ...\n")
    out.append(f"def {fn.py_name}({impl_params}) -> {impl_ret}:\n")
    out.append(docstring(fn))
    out.append(f"    return {call_expr(fn, 'args', 'options')}\n")
    return "".join(out)


def call_expr(fn: Function, args: str, options: str) -> str:
    name = fn.sql_name
    ext = f', "{fn.extension}"' if fn.extension else ""
    return {
        "scalar": f'_rt.scalar("{name}", {args}{ext})',
        "aggregate": f'_rt.aggregate("{name}", {args}, distinct, order_by{ext})',
        "window": f'_rt.window("{name}", {args}, ignore_nulls, order_by{ext})',
        "table": f'_rt.table("{name}", {args}, {options}{ext})',
    }[fn.kind]


def _call_args(params: str) -> tuple[list[str], list[str]]:
    """Split a rendered parameter list into positional names and keyword option names."""
    pos, opts, kw = [], [], False
    for part in _split_top(params.replace("[", "(").replace("]", ")")):
        if not part:
            continue
        if part in ("/",):
            continue
        if part == "*" or part.startswith("*args"):
            kw = True
            continue
        name = part.split(":")[0].strip()
        if name in ("distinct", "order_by", "ignore_nulls"):
            continue
        (opts if kw else pos).append(name)
    return pos, opts


HEADER = '''"""{title}

Generated by scripts/generate_functions.py from DuckDB {version}. Do not edit by hand.
"""

# ruff: noqa
# pyright: reportOverlappingOverload=false, reportInvalidTypeVarUse=false

from __future__ import annotations

import datetime as _dt
from decimal import Decimal as _PyDecimal
from typing import Any as _Any, overload as _overload
from uuid import UUID as _UUID

from shapely.geometry.base import BaseGeometry as _Geom

from parrotlet import sqltypes as _t
from parrotlet.expr import AggregateFunc as _A, Expr as _E, Func as _F, WindowFunc as _W
from parrotlet.functions import _runtime as _rt
from parrotlet.functions._runtime import (
    LambdaArg as _LambdaArg,
    OrderBy as _OrderBy,
    PyDict as _PyDict,
    PyList as _PyList,
    PyScalar as _PyScalar,
    TableFunction as _TableFunction,
    Value as _Value,
)

'''

TITLES = {
    "_core": "Typed DuckDB functions (core and builtin extensions).",
    "tables": 'Typed DuckDB table functions, for use in FROM: `select().from_(read_parquet("x.parquet").as_("t"))`.',
    "spatial": "Typed functions of the DuckDB spatial extension. Run `INSTALL spatial; LOAD spatial` before use.",
}


def write_module(module: str, fns: list[Function], version: str, reexports: list[str] = ()) -> Path:  # type: ignore[assignment]
    by_name = {f.py_name: f for f in fns}
    body, aliases = [], []
    for fn in sorted(fns, key=lambda f: f.py_name):
        target = fn.alias_of and py_identifier(fn.alias_of)
        if target and target in by_name and by_name[target].kind == fn.kind and target != fn.py_name:
            aliases.append(f"{fn.py_name} = {target}\n")
            continue
        body.append(render_function(fn))
    names = sorted([*(f.py_name for f in fns), *reexports])
    text = HEADER.format(title=TITLES[module], version=version)
    text += "__all__ = [\n" + "".join(f'    "{n}",\n' for n in names) + "]\n\n\n"
    text += "\n\n".join(body)
    if aliases:
        text += "\n\n# aliases\n" + "".join(aliases)
    if reexports:
        text += "\n\n# core ST_* functions (they do not need the spatial extension)\n"
        text += "".join(f"from parrotlet.functions._core import {n} as {n}\n" for n in reexports)
    path = OUT / f"{module}.py"
    path.write_text(text, encoding="utf-8")
    return path


def main() -> None:
    version, functions = load()
    modules: dict[str, list[Function]] = defaultdict(list)
    for fn in functions.values():
        modules[fn.module].append(fn)
    spatial_names = {f.py_name for f in modules["spatial"]}
    core_st = sorted(
        f.py_name for f in modules["_core"] if f.py_name.startswith("st_") and f.py_name not in spatial_names
    )
    paths = [write_module(m, fns, version, core_st if m == "spatial" else []) for m, fns in modules.items()]
    subprocess.run(["uvx", "ruff", "format", *map(str, paths)], check=True)
    for m, fns in sorted(modules.items()):
        print(f"{m}: {len(fns)} functions")


if __name__ == "__main__":
    main()
