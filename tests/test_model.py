import datetime
from collections.abc import Sequence
from decimal import Decimal

import duckdb
import pytest

from parrotlet import (
    Check,
    Column,
    Constraint,
    ForeignKey,
    Model,
    PrimaryKey,
    Unique,
    aliased,
    column,
    create_table,
    delete,
    insert,
    select,
    table,
    update,
)
from parrotlet import datatype as dt
from parrotlet import functions as F


class User(Model, table="users"):
    """Matches the `users` table created in conftest."""

    id: Column[int] = column(dt.INTEGER, primary_key=True)
    name: Column[str | None]
    age: Column[int | None] = column(dt.INTEGER, default=None)
    dept: Column[str | None] = column(default=None)


class Order(Model, table="orders"):
    id: Column[int] = column(dt.INTEGER)
    user_id: Column[int] = column(dt.INTEGER, references=User.id)
    amount: Column[Decimal] = column(dt.DECIMAL(10, 2))
    ts: Column[datetime.datetime]


class Item(Model, table="items", schema="main"):
    id: Column[int] = column(dt.INTEGER, primary_key=True)
    name: Column[str] = column(unique=True)
    price: Column[Decimal] = column(dt.DECIMAL(10, 2), default=Decimal(0), check=lambda c: c.price >= 0)
    tags: Column[list[str]] = column(default_factory=lambda: ["new"], server_default=["new"])
    note: Column[str | None] = column(default="it's")
    created: Column[datetime.datetime] = column(default=datetime.datetime(2026, 1, 1))
    owner: Column[int | None] = column(dt.INTEGER, references="users.id", default=None)
    type_: Column[str | None] = column(name="type", default=None)
    doubled: Column[Decimal | None] = column(
        dt.DECIMAL(12, 2),
        generated=lambda c: c.price * 2,
        init=False,
        default=None,
    )


class Pair(Model):
    a: Column[int]
    b: Column[int]
    user_id: Column[int | None] = column(dt.INTEGER, default=None)

    @classmethod
    def constraints(cls) -> Sequence[Constraint]:
        return (
            PrimaryKey(cls.a, cls.b),
            Unique("b", cls.user_id),
            Check(cls.a < cls.b),
            ForeignKey(cls.user_id, User.id),
        )


class Employee(Model, table="employees"):
    id: Column[int] = column(primary_key=True)
    name: Column[str]
    boss_id: Column[int | None] = column(references="employees.id", default=None)


class Timestamped:
    created_at: Column[datetime.datetime] = column(default=F.now())


class Base(Model, abstract=True):
    id: Column[int] = column(primary_key=True)


class Note(Base, Timestamped, table="notes"):
    body: Column[str]


def test_column_access_is_qualified() -> None:
    assert User.id.sql == '"users"."id"'
    assert Item.name.sql == '"main"."items"."name"'
    assert Item.type_.sql == '"main"."items"."type"'
    assert (User.age > 20).sql == '("users"."age" > ?)'


def test_instances_are_rows() -> None:
    u = User(id=1, name="alice")
    assert (u.id, u.name, u.age, u.dept) == (1, "alice", None, None)
    assert u == User(id=1, name="alice", age=None)
    assert u != User(id=2, name="alice")
    assert repr(u) == "User(id=1, name='alice', age=None, dept=None)"
    assert u.to_row() == {"id": 1, "name": "alice", "age": None, "dept": None}
    u.age = 30
    assert u.to_dict()["age"] == 30
    with pytest.raises(TypeError, match="missing keyword argument 'name'"):
        User(id=1)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="unexpected"):
        User(id=1, name="a", bogus=1)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="not an init argument"):
        Item(id=1, name="x", doubled=Decimal(1))  # type: ignore[call-arg]
    assert Item(id=1, name="x").tags == ["new"]


def test_type_inference() -> None:
    class Kinds(Model):
        a: Column[bool]
        b: Column[int]
        c: Column[float]
        d: Column[Decimal]
        e: Column[str | None]
        f: Column[bytes]
        g: Column[datetime.date]
        h: Column[datetime.datetime]
        i: Column[datetime.timedelta]
        j: Column[list[int]]
        k: Column[dict[str, float]]
        plain: str

    assert create_table(Kinds).sql == (
        'CREATE TABLE "kinds" ("a" BOOLEAN NOT NULL, "b" BIGINT NOT NULL, "c" DOUBLE NOT NULL, '
        '"d" DECIMAL(18, 3) NOT NULL, "e" VARCHAR, "f" BLOB NOT NULL, "g" DATE NOT NULL, "h" TIMESTAMP NOT NULL, '
        '"i" INTERVAL NOT NULL, "j" BIGINT[] NOT NULL, "k" MAP(VARCHAR, DOUBLE) NOT NULL, "plain" VARCHAR NOT NULL)'
    )
    with pytest.raises(TypeError, match="Cannot infer"):

        class Bad(Model):
            x: Column[object]


def test_default_tablename_is_snake_case() -> None:
    assert table(Pair).name == "pair"

    class OrderLine(Model):
        id: Column[int]

    assert table(OrderLine).name == "order_line"


def test_class_keywords() -> None:
    with pytest.raises(TypeError, match="cannot set table"):

        class Bad(Model, abstract=True, table="bad"):
            id: Column[int]

    class Child(Item):
        extra: Column[int | None] = column(default=None)

    assert table(Child).ref().sql == '"main"."items"'
    assert [c.name for c in Child.__columns__][-1] == "extra"


def test_column_named_constraints_is_rejected() -> None:
    with pytest.raises(TypeError, match="constraints_"):

        class Bad(Model):
            constraints: Column[int]  # pyright: ignore[reportIncompatibleMethodOverride]

    class Ok(Model):
        constraints_: Column[int] = column(name="constraints")

    assert Ok.constraints_.sql == '"ok"."constraints"'


def test_model_without_columns_fails() -> None:
    with pytest.raises(TypeError, match="no columns"):

        class Empty(Model):
            pass


def test_create_table_from_model(con: duckdb.DuckDBPyConnection) -> None:
    q = create_table(Item).if_not_exists()
    built = q.build()
    assert built.params == ()
    assert built.sql == (
        'CREATE TABLE IF NOT EXISTS "main"."items" ('
        '"id" INTEGER PRIMARY KEY, '
        '"name" VARCHAR NOT NULL UNIQUE, '
        '"price" DECIMAL(10, 2) NOT NULL DEFAULT 0::DECIMAL CHECK (("price" >= 0)), '
        "\"tags\" VARCHAR[] NOT NULL DEFAULT ['new'], "
        "\"note\" VARCHAR DEFAULT 'it''s', "
        "\"created\" TIMESTAMP NOT NULL DEFAULT '2026-01-01T00:00:00'::TIMESTAMP, "
        '"owner" INTEGER REFERENCES "users" ("id"), '
        '"type" VARCHAR, '
        '"doubled" DECIMAL(12, 2) GENERATED ALWAYS AS (("price" * 2)) VIRTUAL)'
    )
    q.execute(con)
    insert(Item, ["id", "name", "owner"]).values((1, "pen", 1)).execute(con)
    assert select(Item.price, Item.tags, Item.note, Item.doubled).from_(Item).execute(con).fetchone() == (
        0,
        ["new"],
        "it's",
        0,
    )
    with pytest.raises(duckdb.ConstraintException):
        insert(Item, ["id", "name", "price"]).values((2, "bad", -1)).execute(con)


def test_fetch_instances(con: duckdb.DuckDBPyConnection) -> None:
    create_table(Item).execute(con)
    insert(Item, ["id", "name"]).values((1, "n1"), (2, "n2")).execute(con)
    rows = select(Item).from_(Item).order_by(Item.id).fetch(Item, con)
    assert [r.name for r in rows] == ["n1", "n2"]
    assert rows[0].doubled == 0
    assert isinstance(rows[0], Item)


def test_table_constraints(con: duckdb.DuckDBPyConnection) -> None:
    q = create_table(Pair)
    assert q.sql == (
        'CREATE TABLE "pair" ("a" BIGINT NOT NULL, "b" BIGINT NOT NULL, "user_id" INTEGER, '
        'PRIMARY KEY ("a", "b"), UNIQUE ("b", "user_id"), CHECK (("a" < "b")), '
        'FOREIGN KEY ("user_id") REFERENCES "users" ("id"))'
    )
    q.execute(con)
    insert(Pair).values(Pair(a=1, b=2, user_id=1)).execute(con)
    with pytest.raises(duckdb.ConstraintException):
        insert(Pair).values(Pair(a=3, b=2)).execute(con)


def test_constraints_are_inherited_and_extended() -> None:
    class Triple(Pair, table="triples"):
        c: Column[int]

        @classmethod
        def constraints(cls) -> Sequence[Constraint]:
            return (*super().constraints(), Check(cls.b < cls.c))

    sql = create_table(Triple).sql
    assert 'PRIMARY KEY ("a", "b")' in sql
    assert sql.endswith('REFERENCES "users" ("id"), CHECK (("b" < "c")))')


def test_self_reference_and_aliased(con: duckdb.DuckDBPyConnection) -> None:
    assert '"boss_id" BIGINT REFERENCES "employees" ("id")' in create_table(Employee).sql
    create_table(Employee).execute(con)
    insert(Employee).values(Employee(id=1, name="boss")).execute(con)
    insert(Employee).values(Employee(id=2, name="worker", boss_id=1)).execute(con)

    Boss = aliased(Employee, "boss")
    assert Boss.id.sql == '"boss"."id"'
    q = select(Employee.name, Boss.name.as_("boss")).from_(Employee).join(Boss, Employee.boss_id == Boss.id)
    assert ' INNER JOIN "employees" AS "boss" ON ' in q.sql
    assert q.execute(con).fetchall() == [("worker", "boss")]
    assert Employee.id.sql == '"employees"."id"'


def test_abstract_base_mixin_and_server_default(con: duckdb.DuckDBPyConnection) -> None:
    assert [c.name for c in Note.__columns__] == ["created_at", "id", "body"]
    assert create_table(Note).sql == (
        'CREATE TABLE "notes" ("created_at" TIMESTAMP NOT NULL DEFAULT get_current_timestamp(), '
        '"id" BIGINT PRIMARY KEY, "body" VARCHAR NOT NULL)'
    )
    create_table(Note).execute(con)
    note = Note(id=1, body="hi")
    insert(Note).values(note).execute(con)  # created_at is filled in by the database (DEFAULT)
    (row,) = select(Note).from_(Note).fetch(Note, con)
    assert isinstance(row.created_at, datetime.datetime)


def test_queries_with_models(con: duckdb.DuckDBPyConnection) -> None:
    q = (
        select(User.name, F.sum(Order.amount).as_("total"))
        .from_(User)
        .join(Order, User.id == Order.user_id)
        .where(User.dept == "eng")
        .group_by(User.name)
        .order_by(User.name)
    )
    assert [(n, float(t)) for n, t in q.execute(con).fetchall()] == [("alice", 150.5), ("bob", 20.0)]
    assert select(User).from_(User).where(User.id == 1).sql == 'SELECT "users".* FROM "users" WHERE ("users"."id" = ?)'
    assert select(User).from_(User).where(User.id == 1).fetch(User, con) == [
        User(id=1, name="alice", age=30, dept="eng"),
    ]


def test_dml_with_models(con: duckdb.DuckDBPyConnection) -> None:
    insert(User).values(User(id=9, name="zoe", age=20, dept="ops")).execute(con)
    assert update(User).set({User.age: User.age + 1}).where(User.id == 9).returning(User.age).execute(
        con,
    ).fetchall() == [(21,)]
    assert delete(User).where(User.dept == "ops").returning(User.name).execute(con).fetchall() == [("zoe",)]


def test_create_table_as_and_validation(con: duckdb.DuckDBPyConnection) -> None:
    q = create_table("eng").or_replace().as_(select(User.id, User.name).from_(User).where(User.dept == "eng"))
    assert q.sql.startswith('CREATE OR REPLACE TABLE "eng" AS SELECT')
    q.execute(con)
    assert con.execute("SELECT count(*) FROM eng").fetchone() == (2,)
    with pytest.raises(ValueError, match="needs a Model"):
        _ = create_table("x").sql
    with pytest.raises(ValueError, match="cannot be combined"):
        _ = create_table(Pair).or_replace().if_not_exists().sql


def test_explicit_complex_types(con: duckdb.DuckDBPyConnection) -> None:
    class Complex(Model):
        s: Column[dict[str, object]] = column(dt.STRUCT(x=dt.INTEGER, y="VARCHAR"))
        m: Column[dict[str, float]]
        e: Column[str] = column(dt.ENUM("a", "b"))
        arr: Column[list[float]] = column(dt.ARRAY(dt.FLOAT, 3))

    q = create_table(Complex).temporary()
    assert q.sql.startswith('CREATE TEMPORARY TABLE "complex" ("s" STRUCT("x" INTEGER, "y" VARCHAR) NOT NULL, ')
    q.execute(con)
    insert(Complex).values(Complex(s={"x": 1, "y": "z"}, m={"k": 1.5}, e="b", arr=[1.0, 2.0, 3.0])).execute(con)
    assert select(Complex.s["y"], Complex.e).from_(Complex).execute(con).fetchone() == ("z", "b")


def test_table_of_model(con: duckdb.DuckDBPyConnection) -> None:
    users = table(User)
    assert users.name == "users"
    assert select(users.star(exclude=["dept"])).from_(User).where(User.id == 1).fetchall(con) == [(1, "alice", 30)]
    u = table(User, alias="u")
    assert u.c.name.sql == '"u"."name"'
    assert select(u.c.name).from_(u).where(u.c.id == 2).fetchall(con) == [("bob",)]
    assert select(F.count()).from_(table(User).tablesample(rows=2)).fetchall(con) == [(2,)]
    with pytest.raises(TypeError, match="not a Model"):
        table(int)  # type: ignore[call-overload]
