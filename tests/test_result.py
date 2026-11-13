from dataclasses import dataclass
from typing import NamedTuple, TypedDict

import duckdb
import pytest
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

import parrotlet.functions as fn
import parrotlet.type as qlt
from parrotlet import Column, Model, column, create_table, func, insert, select


class User(Model, table="users"):
    id: Column[int] = column(qlt.Integer, primary_key=True)
    name: Column[str | None]
    age: Column[int | None] = column(qlt.Integer)
    dept: Column[str | None]


@dataclass
class UserRow:
    id: int
    name: str
    age: int | None


class DeptCount(NamedTuple):
    dept: str | None
    n: int


class NameDict(TypedDict):
    name: str


def test_fetch_dataclass(con: duckdb.DuckDBPyConnection) -> None:
    rows = select(User.id, User.name, User.age).from_(User).order_by(User.id).limit(2).fetch_as(UserRow, con)
    assert rows == [UserRow(1, "alice", 30), UserRow(2, "bob", 25)]


def test_fetch_namedtuple_with_alias(con: duckdb.DuckDBPyConnection) -> None:
    q = select(User.dept, fn.count().as_("n")).from_(User).group_by(User.dept).order_by(User.dept)
    assert q.fetch_as(DeptCount, con) == [DeptCount("eng", 2), DeptCount("sales", 2), DeptCount(None, 1)]


def test_fetch_typeddict_and_one(con: duckdb.DuckDBPyConnection) -> None:
    assert select(User.name).from_(User).where(User.id == 3).fetch_one_as(NameDict, con) == {"name": "carol"}
    assert select(User.name).from_(User).where(User.id == 99).fetch_one_as(NameDict, con) is None


def test_fetch_unknown_column(con: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(ValueError, match="no matching field"):
        select(User.id, User.dept).from_(User).fetch_as(UserRow, con)


def test_fetch_returning(con: duckdb.DuckDBPyConnection) -> None:
    q = insert(User, ["id", "name", "age"]).values((10, "zed", 50)).returning(User.id, User.name, User.age)
    assert q.fetch_as(UserRow, con) == [UserRow(10, "zed", 50)]


def test_fetch_without_result_set(con: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(ValueError, match="returning"):
        insert(User, ["id"]).values((11,)).fetch_as(UserRow, con)


class Place(Model, table="places"):
    id: Column[int] = column(qlt.Integer)
    geom: Column[BaseGeometry | None]


@dataclass
class PlaceRow:
    id: int
    geom: BaseGeometry | None


def test_fetch_decodes_geometry(con: duckdb.DuckDBPyConnection) -> None:
    create_table(Place).execute(con)
    insert(Place).values((1, Point(1, 2)), (2, None)).execute(con)
    rows = select(Place.id, Place.geom).from_(Place).order_by(Place.id).fetch_as(PlaceRow, con)
    assert rows == [PlaceRow(1, Point(1, 2)), PlaceRow(2, None)]
    _ = func  # untyped escape hatch still importable
