import duckdb
import pytest

from parrotlet import DEFAULT, delete, excluded, func, insert, select, table, update

users = table("users")
orders = table("orders")
u = users.c
o = orders.c


def count(con: duckdb.DuckDBPyConnection, where: object = None) -> int:
    q = select(func.count()).from_(users)
    if where is not None:
        q = q.where(where)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
    row = q.execute(con).fetchone()
    assert row is not None
    return row[0]


# INSERT ---------------------------------------------------------------------------------------------------------------


def test_insert_tuples(con: duckdb.DuckDBPyConnection) -> None:
    q = insert(users, ["id", "name"]).values((10, "zed"), (11, "yan"))
    assert q.sql == 'INSERT INTO "users" ("id", "name") VALUES (?, ?), (?, ?)'
    assert q.params == (10, "zed", 11, "yan")
    q.execute(con)
    assert count(con) == 7


def test_insert_dicts(con: duckdb.DuckDBPyConnection) -> None:
    q = insert("users").values({"id": 20, "name": "a", "age": 1}, {"age": 2, "id": 21, "name": "b"})
    assert q.sql == 'INSERT INTO "users" ("id", "name", "age") VALUES (?, ?, ?), (?, ?, ?)'
    assert q.params == (20, "a", 1, 21, "b", 2)
    q.execute(con)
    assert select(u.age).from_(users).where(u.id == 21).execute(con).fetchone() == (2,)


def test_insert_mismatched_rows() -> None:
    with pytest.raises(ValueError, match="do not match"):
        insert("users").values({"id": 1}, {"name": "x"})
    with pytest.raises(ValueError, match="columns were given"):
        insert("users", ["id", "name"]).values((1,))


def test_insert_default_keyword(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE TABLE d (id INTEGER, v VARCHAR DEFAULT 'dflt')")
    insert("d").values((1, DEFAULT)).execute(con)
    assert con.execute("SELECT v FROM d").fetchone() == ("dflt",)


def test_insert_select_by_name(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("CREATE TABLE names (name VARCHAR, id INTEGER)")
    q = insert("names").by_name().select(select(u.id, u.name).from_(users).where(u.dept == "eng"))
    assert q.sql.startswith('INSERT INTO "names" BY NAME SELECT')
    q.execute(con)
    assert con.execute("SELECT name, id FROM names ORDER BY id").fetchall() == [("alice", 1), ("bob", 2)]


def test_insert_on_conflict_do_nothing(con: duckdb.DuckDBPyConnection) -> None:
    q = insert(users, ["id", "name"]).values((1, "dup")).on_conflict_do_nothing("id")
    assert q.sql.endswith('ON CONFLICT ("id") DO NOTHING')
    q.execute(con)
    assert select(u.name).from_(users).where(u.id == 1).execute(con).fetchone() == ("alice",)


def test_insert_on_conflict_do_update_returning(con: duckdb.DuckDBPyConnection) -> None:
    q = (
        insert(users, ["id", "name", "age"])
        .values((1, "alice2", 99))
        .on_conflict_do_update("id", {"name": excluded.c.name}, age=excluded.c.age + 1)
        .returning(u.id, "name", "age")
    )
    assert 'ON CONFLICT ("id") DO UPDATE SET "name" = "excluded"."name", "age" = ("excluded"."age" + ?)' in q.sql
    assert q.execute(con).fetchall() == [(1, "alice2", 100)]


def test_insert_or_replace_or_ignore(con: duckdb.DuckDBPyConnection) -> None:
    insert(users, ["id", "name"]).values((2, "bob2")).or_replace().execute(con)
    assert select(u.name).from_(users).where(u.id == 2).execute(con).fetchone() == ("bob2",)
    q = insert(users, ["id", "name"]).values((2, "bob3")).or_ignore()
    assert q.sql.startswith("INSERT OR IGNORE INTO")
    q.execute(con)
    assert select(u.name).from_(users).where(u.id == 2).execute(con).fetchone() == ("bob2",)


def test_insert_without_source_fails() -> None:
    with pytest.raises(ValueError, match="needs"):
        _ = insert("users").sql


def test_insert_with_cte(con: duckdb.DuckDBPyConnection) -> None:
    src = select(func.unnest([100, 101]).as_("id")).cte("src")
    insert(users, ["id"]).with_(src).select(select(src.c.id).from_(src)).execute(con)
    assert count(con) == 7


# UPDATE ---------------------------------------------------------------------------------------------------------------


def test_update(con: duckdb.DuckDBPyConnection) -> None:
    q = update(users).set({u.age: u.age + 1}, dept="ENG").where(u.dept == "eng").returning(u.id, u.age)
    built = q.build()
    assert built.sql == (
        'UPDATE "users" SET "age" = ("users"."age" + ?), "dept" = ? WHERE ("users"."dept" = ?)'
        ' RETURNING "users"."id", "users"."age"'
    )
    assert built.params == (1, "ENG", "eng")
    assert sorted(q.execute(con).fetchall()) == [(1, 31), (2, 26)]
    assert count(con, u.dept == "ENG") == 2


def test_update_from(con: duckdb.DuckDBPyConnection) -> None:
    totals = select(o.user_id, func.sum(o.amount).as_("total")).from_(orders).group_by(o.user_id).subquery("t")
    q = update(users).set(age=totals.c.total.cast("INTEGER")).from_(totals).where(u.id == totals.c.user_id)
    q.execute(con)
    assert select(u.age).from_(users).where(u.id == 3).execute(con).fetchone() == (1000,)


def test_update_requires_set() -> None:
    with pytest.raises(ValueError, match="set"):
        _ = update("users").sql


# DELETE ---------------------------------------------------------------------------------------------------------------


def test_delete(con: duckdb.DuckDBPyConnection) -> None:
    q = delete(users).where(u.age.is_null()).returning("name")
    assert q.sql == 'DELETE FROM "users" WHERE ("users"."age" IS NULL) RETURNING "name"'
    assert q.execute(con).fetchall() == [("dave",)]
    assert count(con) == 4


def test_delete_using(con: duckdb.DuckDBPyConnection) -> None:
    q = delete(orders).using(users).where(o.user_id == u.id, u.name == "alice")
    assert (
        q.sql
        == 'DELETE FROM "orders" USING "users" WHERE (("orders"."user_id" = "users"."id") AND ("users"."name" = ?))'
    )
    q.execute(con)
    assert con.execute("SELECT count(*) FROM orders").fetchone() == (2,)
