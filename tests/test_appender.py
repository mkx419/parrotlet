import datetime
from collections.abc import Iterator

import duckdb
import pytest
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from parrotlet import Appender, Column, Database, Model, column
from parrotlet import functions as F


class User(Model, table="users", schema="main"):
    id: Column[int] = column(primary_key=True)
    name: Column[str]
    age: Column[int | None] = column(default=None)
    home: Column[BaseGeometry | None] = column(default=None)
    joined: Column[datetime.datetime] = column(default=F.now())


@pytest.fixture
def db() -> Iterator[Database]:
    with Database() as database:
        database.register(User)
        yield database


def rows(db: Database) -> list[tuple[object, ...]]:
    return db.select(User.id, User.name, User.age).from_(User).order_by(User.id).fetchall()


def test_insert_models_mappings_and_sequences(db: Database) -> None:
    with db.appender(User) as app:
        assert app.columns == ("id", "name", "age", "home")  # `joined` is left to its database default
        app.append(User(id=1, name="alice", age=30, home=Point(1, 2)))
        app.extend(User(id=i, name=f"u{i}") for i in (2, 3))
        app.append({"id": 4, "name": "map", "age": None, "home": None})
        app.append((5, "seq", 50, None))
    assert rows(db) == [(1, "alice", 30), (2, "u2", None), (3, "u3", None), (4, "map", None), (5, "seq", 50)]
    (alice,) = db.from_(User).where(User.id == 1).fetch(User)
    assert alice.home == Point(1, 2)
    assert isinstance(alice.joined, datetime.datetime)


def test_upsert_update_delete(db: Database) -> None:
    with db.appender(User) as app:
        app.extend(User(id=i, name=f"u{i}", age=i) for i in (1, 2, 3))
    with db.appender(User, action="upsert") as app:
        app.append(User(id=1, name="one", age=10))
        app.append(User(id=9, name="nine"))
    with db.appender(User, action="update", columns=[User.id, User.age]) as app:
        app.append(User(id=2, name="ignored", age=20))
    with db.appender(User, action="delete") as app:
        app.append(User(id=3, name="ignored"))
    assert rows(db) == [(1, "one", 10), (2, "u2", 20), (9, "nine", None)]


def test_batch_size_flushes(db: Database) -> None:
    app = db.appender(User, batch_size=2)
    app.append(User(id=1, name="a"))
    assert rows(db) == []
    app.append(User(id=2, name="b"))
    assert len(rows(db)) == 2


def test_exception_discards_buffer(db: Database) -> None:
    with pytest.raises(RuntimeError), db.appender(User) as app:
        app.append(User(id=1, name="a"))
        raise RuntimeError
    assert rows(db) == []


def test_plain_table_and_explicit_columns() -> None:
    con = duckdb.connect()
    con.execute("CREATE TABLE t (a INTEGER, b VARCHAR, c INTEGER DEFAULT 7)")
    with Appender(con, "t", columns=["a", "b"]) as app:
        app.append((1, "x"))
        app.append({"a": 2, "b": "y"})
    assert con.execute("SELECT * FROM t ORDER BY a").fetchall() == [(1, "x", 7), (2, "y", 7)]


def test_errors(db: Database) -> None:
    with pytest.raises(ValueError, match="key"):
        db.appender("t", action="delete")
    app = db.appender(User)
    with pytest.raises(ValueError, match="database-side default"):
        app.append(User(id=1, name="a", joined=datetime.datetime(2026, 1, 1)))
    with pytest.raises(ValueError, match="DEFAULT"):
        db.appender(User, columns=["id", "name", "joined"]).append(User(id=1, name="a"))
