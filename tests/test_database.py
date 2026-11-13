import datetime
from collections.abc import Iterator

import duckdb
import pytest
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

import parrotlet.functions as fn
import parrotlet.type as qlt
from parrotlet import Column, Database, Model, col, column, create_view, func, select


@pytest.fixture
def db() -> Iterator[Database]:
    with Database() as database:
        yield database


def test_register_creates_table(db: Database) -> None:
    @db.register
    class User(Model, table="users"):
        id: Column[int] = column(primary_key=True)
        name: Column[str]
        joined: Column[datetime.datetime] = column(default=fn.now())

    db.insert(User).values(User(id=1, name="alice"), User(id=2, name="bob")).execute()
    rows = db.from_(User).where(User.id == 2).fetch_as(User)
    assert [(u.id, u.name) for u in rows] == [(2, "bob")]
    assert isinstance(rows[0].joined, datetime.datetime)
    db.register(User)  # idempotent: CREATE TABLE IF NOT EXISTS


def test_bound_statements(db: Database) -> None:
    @db.register
    class Item(Model, table="items"):
        id: Column[int] = column(primary_key=True)
        qty: Column[int] = column(default=0)

    db.insert(Item).values(Item(id=1), Item(id=2, qty=5)).execute()
    db.update(Item).set({Item.qty: Item.qty + 1}).where(Item.id == 1).execute()
    assert db.select(Item.id, Item.qty).from_(Item).order_by(Item.id).fetchall() == [(1, 1), (2, 5)]
    assert db.from_(Item).where(Item.qty > 2).fetch_as(Item) == [Item(id=2, qty=5)]
    assert db.select(Item.id).from_(Item).union(select(Item.id).from_(Item)).fetchall() is not None
    db.delete(Item).where(Item.id == 1).execute()
    assert db.select(fn.count()).from_(Item).fetchone() == (1,)
    db.truncate(Item).execute()
    assert db.select(fn.count()).from_(Item).fetchone() == (0,)


def test_execute_other_statements_and_raw_sql(db: Database) -> None:
    n = 3
    db.sql(t"CREATE TABLE t AS SELECT * FROM range({n}) r(x)")
    db.execute(create_view("v", select().from_("t").where(func.mod(col("x"), 2) == 0)))
    assert db.sql(t"SELECT count(*) FROM v").fetchone() == (2,)
    assert db.bind(select(func.max(col("x"))).from_("t")).fetchone() == (2,)


def test_spatial_is_loaded_automatically(db: Database) -> None:
    def loaded() -> bool:
        row = db.sql(t"SELECT loaded FROM duckdb_extensions() WHERE extension_name = 'spatial'").fetchone()
        return bool(row and row[0])

    assert not loaded()
    assert db.select(fn.spatial.st_distance(fn.spatial.st_point(0, 0), fn.spatial.st_point(3, 4))).fetchone() == (5.0,)
    assert loaded()


def test_untyped_extension_function_triggers_install() -> None:
    with Database() as db:
        # func.<name> carries no extension info: the "exists in the spatial extension" error triggers the install
        assert db.select(func.st_area(func.st_geomfromtext("POLYGON((0 0,1 0,1 1,0 0))"))).fetchone() == (0.5,)


def test_auto_install_can_be_disabled() -> None:
    with Database(auto_install=False) as db, pytest.raises(duckdb.Error, match="spatial"):
        db.select(func.st_area(func.st_geomfromtext("POINT(0 0)"))).fetchone()


def test_spatial_model_types(db: Database) -> None:
    @db.register
    class Place(Model, table="places"):
        id: Column[int] = column(primary_key=True)
        geom: Column[BaseGeometry]
        pt: Column[object | None] = column(qlt.Point2D, default=None)

    db.insert(Place).values(Place(id=1, geom=Point(1, 2))).execute()
    (place,) = db.from_(Place).fetch_as(Place)
    assert place.geom == Point(1, 2)
    assert db.select(fn.spatial.st_x(Place.geom)).from_(Place).fetchone() == (1.0,)


def test_database_on_existing_connection() -> None:
    con = duckdb.connect()
    db = Database(connection=con)
    assert db.select(fn.upper("x")).fetchone() == ("X",)
    assert db.connection is con
