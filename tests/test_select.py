import duckdb
import pytest

from parrotlet import col, cube, from_, func, grouping_sets, lit, rollup, select, table, table_function

users = table("users")
orders = table("orders")
u = users.c
o = orders.c


def test_select_star_default() -> None:
    assert select().from_("users").sql == 'SELECT * FROM "users"'
    assert from_("users").sql == 'SELECT * FROM "users"'


def test_basic_select(con: duckdb.DuckDBPyConnection) -> None:
    q = select(u.id, u.name).from_(users).where(u.age > 28).order_by(u.id.desc()).limit(2)
    built = q.build()
    assert built.sql == (
        'SELECT "users"."id", "users"."name" FROM "users" WHERE ("users"."age" > ?) ORDER BY "users"."id" DESC LIMIT ?'
    )
    assert built.params == (28, 2)
    assert q.execute(con).fetchall() == [(5, "eve"), (3, "carol")]


def test_string_column_names(con: duckdb.DuckDBPyConnection) -> None:
    q = select("name", "age").from_("users").where(col("id") == 2)
    assert q.sql == 'SELECT "name", "age" FROM "users" WHERE ("id" = ?)'
    assert q.execute(con).fetchall() == [("bob", 25)]


def test_builder_is_immutable() -> None:
    base = select(u.id).from_(users)
    filtered = base.where(u.age > 1)
    assert "WHERE" not in base.sql
    assert "WHERE" in filtered.sql


def test_where_calls_are_anded(con: duckdb.DuckDBPyConnection) -> None:
    q = select(u.name).from_(users).where(u.dept == "eng").where(u.age < 30)
    assert q.sql.endswith('WHERE (("users"."dept" = ?) AND ("users"."age" < ?))')
    assert q.execute(con).fetchall() == [("bob",)]


def test_distinct_and_distinct_on(con: duckdb.DuckDBPyConnection) -> None:
    assert select(u.dept).distinct().from_(users).where(u.dept.is_not_null()).order_by(u.dept).execute(
        con,
    ).fetchall() == [("eng",), ("sales",)]
    q = select(u.dept, u.name).distinct(on=u.dept).from_(users).order_by(u.dept, u.age.desc())
    assert q.sql.startswith('SELECT DISTINCT ON ("users"."dept") ')
    assert q.execute(con).fetchall() == [("eng", "alice"), ("sales", "carol"), (None, "eve")]


def test_joins(con: duckdb.DuckDBPyConnection) -> None:
    q = (
        select(u.name, func.sum(o.amount).as_("total"))
        .from_(users)
        .join(orders, u.id == o.user_id)
        .group_by(u.name)
        .order_by(u.name)
    )
    assert ' INNER JOIN "orders" ON ("users"."id" = "orders"."user_id")' in q.sql
    assert [(n, float(t)) for n, t in q.execute(con).fetchall()] == [("alice", 150.5), ("bob", 20.0), ("carol", 999.99)]

    left = select(u.name, o.id).from_(users).left_join(orders, u.id == o.user_id).where(o.id.is_null()).order_by(u.id)
    assert left.execute(con).fetchall() == [("dave", None), ("eve", None)]


def test_join_with_alias_and_using(con: duckdb.DuckDBPyConnection) -> None:
    a = table("users").as_("a")
    b = table("users").as_("b")
    q = select(a.c.name, b.c.name).from_(a).join(b, using="dept").where(a.c.id < b.c.id).order_by(a.c.id, b.c.id)
    assert 'FROM "users" AS "a" INNER JOIN "users" AS "b" USING ("dept")' in q.sql
    assert q.execute(con).fetchall() == [("alice", "bob"), ("carol", "dave")]


def test_semi_anti_join(con: duckdb.DuckDBPyConnection) -> None:
    semi = select(u.name).from_(users).semi_join(orders, u.id == o.user_id).order_by(u.id)
    assert semi.execute(con).fetchall() == [("alice",), ("bob",), ("carol",)]
    anti = select(u.name).from_(users).anti_join(orders, u.id == o.user_id).order_by(u.id)
    assert anti.execute(con).fetchall() == [("dave",), ("eve",)]


def test_join_on_and_using_conflict() -> None:
    with pytest.raises(ValueError, match="either"):
        select().from_(users).join(orders, u.id == o.user_id, using="id")


def test_group_by_having(con: duckdb.DuckDBPyConnection) -> None:
    q = select(u.dept, func.count().as_("n")).from_(users).group_by(u.dept).having(func.count() >= 2).order_by(u.dept)
    assert q.execute(con).fetchall() == [("eng", 2), ("sales", 2)]


def test_group_by_all_order_by_all(con: duckdb.DuckDBPyConnection) -> None:
    q = select(u.dept, func.max(u.age)).from_(users).group_by_all().order_by_all(nulls="first")
    assert q.sql.endswith("GROUP BY ALL ORDER BY ALL ASC NULLS FIRST")
    assert q.execute(con).fetchall() == [(None, 35), ("eng", 30), ("sales", 41)]


def test_rollup_cube_grouping_sets(con: duckdb.DuckDBPyConnection) -> None:
    r = select(u.dept, func.count()).from_(users).group_by(rollup(u.dept)).order_by_all()
    assert 'GROUP BY ROLLUP ("users"."dept")' in r.sql
    assert len(r.execute(con).fetchall()) == 4
    c = select(u.dept, func.count()).from_(users).group_by(cube(u.dept))
    assert len(c.execute(con).fetchall()) == 4
    g = select(u.dept, u.age, func.count()).from_(users).group_by(grouping_sets([u.dept], [u.age], []))
    assert 'GROUPING SETS (("users"."dept"), ("users"."age"), ())' in g.sql
    assert len(g.execute(con).fetchall()) == 3 + 5 + 1


def test_qualify(con: duckdb.DuckDBPyConnection) -> None:
    rn = func.row_number().over(partition_by=u.dept, order_by=u.age.desc())
    q = select(u.dept, u.name).from_(users).where(u.dept.is_not_null()).qualify(rn == 1).order_by(u.dept)
    assert " QUALIFY " in q.sql
    assert q.execute(con).fetchall() == [("eng", "alice"), ("sales", "carol")]


def test_limit_offset(con: duckdb.DuckDBPyConnection) -> None:
    q = select(u.id).from_(users).order_by(u.id).limit(2, offset=1)
    assert q.sql.endswith("LIMIT ? OFFSET ?")
    assert q.execute(con).fetchall() == [(2,), (3,)]


def test_sample(con: duckdb.DuckDBPyConnection) -> None:
    q = select().from_(users).using_sample(rows=2, method="reservoir", seed=42)
    assert q.sql == 'SELECT * FROM "users" USING SAMPLE 2 ROWS (reservoir, 42)'
    assert len(q.execute(con).fetchall()) == 2
    assert (
        "USING SAMPLE 50 PERCENT (bernoulli)" in select().from_(users).using_sample(percent=50, method="bernoulli").sql
    )


def test_subquery_in_from(con: duckdb.DuckDBPyConnection) -> None:
    totals = select(o.user_id, func.sum(o.amount).as_("total")).from_(orders).group_by(o.user_id).subquery("t")
    q = select(u.name, totals.c.total).from_(users).join(totals, u.id == totals.c.user_id).where(totals.c.total > 100)
    assert sorted(r[0] for r in q.execute(con).fetchall()) == ["alice", "carol"]


def test_scalar_subquery(con: duckdb.DuckDBPyConnection) -> None:
    avg_age = select(func.avg(u.age)).from_(users)
    q = select(u.name).from_(users).where(u.age > avg_age.scalar()).order_by(u.id)
    assert q.execute(con).fetchall() == [("carol",), ("eve",)]


def test_cte(con: duckdb.DuckDBPyConnection) -> None:
    eng = select(u.id, u.name).from_(users).where(u.dept == "eng").cte("eng")
    q = (
        select(eng.c.name, func.count(o.id).as_("n"))
        .with_(eng)
        .from_(eng)
        .left_join(orders, eng.c.id == o.user_id)
        .group_by(eng.c.name)
        .order_by(eng.c.name)
    )
    assert q.sql.startswith('WITH "eng" AS (SELECT')
    assert q.params == ("eng",)
    assert q.execute(con).fetchall() == [("alice", 2), ("bob", 1)]


def test_recursive_cte(con: duckdb.DuckDBPyConnection) -> None:
    nums = table("nums")
    body = select(1).union_all(select(nums.c.n + 1).from_(nums).where(nums.c.n < 5))
    cte = body.cte("nums", columns=["n"])
    q = select(func.sum(cte.c.n)).with_recursive(cte).from_(cte)
    assert q.sql.startswith('WITH RECURSIVE "nums" ("n") AS (')
    assert q.execute(con).fetchone() == (15,)


def test_materialized_cte() -> None:
    c = select(1).cte("x", materialized=True)
    assert select().with_(c).from_(c).sql == 'WITH "x" AS MATERIALIZED (SELECT ?) SELECT * FROM "x"'


def test_set_operations(con: duckdb.DuckDBPyConnection) -> None:
    a = select(u.id).from_(users).where(u.id <= 3)
    b = select(u.id).from_(users).where(u.id >= 3)
    assert a.union(b).order_by("id").execute(con).fetchall() == [(i,) for i in range(1, 6)]
    assert a.union_all(b).execute(con).fetchall().count((3,)) == 2
    assert a.intersect(b).execute(con).fetchall() == [(3,)]
    assert a.except_(b).order_by("id").execute(con).fetchall() == [(1,), (2,)]
    chained = a.union(b).union(select(99))
    assert chained.sql.count("UNION") == 2
    assert len(chained.execute(con).fetchall()) == 6


def test_union_by_name(con: duckdb.DuckDBPyConnection) -> None:
    x = select(lit(1).as_("a"), lit(2).as_("b"))
    y = select(lit(3).as_("b"), lit(4).as_("a"))
    q = x.union(y, all=True, by_name=True)
    assert " UNION ALL BY NAME " in q.sql
    assert sorted(q.execute(con).fetchall()) == [(1, 2), (4, 3)]


def test_table_function(con: duckdb.DuckDBPyConnection) -> None:
    r = table_function(func.range(3), "r")
    q = select(r.c.range).from_(r)
    assert q.sql == 'SELECT "r"."range" FROM range(?) AS "r"'
    assert q.execute(con).fetchall() == [(0,), (1,), (2,)]
    assert from_(func.range(2)).execute(con).fetchall() == [(0,), (1,)]


def test_order_by_nulls(con: duckdb.DuckDBPyConnection) -> None:
    q = select(u.name).from_(users).order_by(u.age.asc(nulls="first")).limit(1)
    assert q.execute(con).fetchall() == [("dave",)]
