"""DuckDB-specific syntax: star modifiers, COLUMNS, list comprehensions, PIVOT, MERGE, COPY, DDL, utilities."""

import datetime
from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

import parrotlet.functions as fn
import parrotlet.type as qlt
from parrotlet import (
    Column,
    Model,
    all_,
    alter_table,
    any_,
    attach,
    col,
    column,
    columns,
    comment_on_column,
    comment_on_table,
    copy_from,
    copy_to,
    create_index,
    create_macro,
    create_schema,
    create_secret,
    create_sequence,
    create_table,
    create_type,
    create_view,
    describe,
    detach,
    drop_macro,
    drop_secret,
    drop_table,
    drop_view,
    file,
    from_,
    func,
    insert,
    list_comprehension,
    lit,
    merge_action,
    merge_into,
    pivot,
    positional,
    pragma,
    range_between,
    rows_between,
    select,
    set_,
    set_variable,
    show_databases,
    show_tables,
    star,
    summarize,
    table,
    tablesample,
    truncate,
    try_,
    unpivot,
    use,
    val,
    values,
)


class T(Model, table="t"):
    id: Column[int] = column(qlt.Integer, primary_key=True)
    name: Column[str | None]
    num_a: Column[int | None] = column(qlt.Integer)
    num_b: Column[int | None] = column(qlt.Integer)
    cat: Column[str | None]
    yr: Column[int | None] = column(qlt.Integer)
    v: Column[int | None] = column(qlt.Integer)
    tags: Column[list[int] | None] = column(qlt.List(qlt.Integer))
    j: Column[str | None] = column(qlt.Json)
    ts: Column[datetime.datetime | None]


@pytest.fixture
def db() -> Iterator[duckdb.DuckDBPyConnection]:
    conn = duckdb.connect()
    create_table(T).execute(conn)
    insert(T).values(
        (1, "x", 2, 3, "a", 2025, 10, [1, 2, 3], '{"a": {"b": 1}}', datetime.datetime(2026, 1, 1)),
        (2, "y", 4, 5, "b", 2026, 20, [4, 5], '{"a": {"b": 2}}', datetime.datetime(2026, 1, 2)),
        (3, "z", 6, 7, "a", 2026, 30, [], '{"a": {"b": 3}}', datetime.datetime(2026, 1, 4)),
    ).execute(conn)
    yield conn
    conn.close()


def names(cur: duckdb.DuckDBPyConnection) -> list[str]:
    assert cur.description is not None
    return [d[0] for d in cur.description]


# star / COLUMNS -------------------------------------------------------------------------------------------------------


def test_star_modifiers(db: duckdb.DuckDBPyConnection) -> None:
    q = select(star(exclude=["name", "j", "tags", "ts"], replace={"v": T.v * 10}, rename={"id": "ident"})).from_(T)
    assert q.sql.startswith(
        'SELECT * EXCLUDE ("name", "j", "tags", "ts") REPLACE (("t"."v" * ?) AS "v") RENAME ("id" AS "ident")',
    )
    cur = q.where(T.id == 1).execute(db)
    assert names(cur) == ["ident", "num_a", "num_b", "cat", "yr", "v"]
    assert cur.fetchall() == [(1, 2, 3, "a", 2025, 100)]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"like": "num%"}, ["num_a", "num_b"]),
        ({"not_like": "num%"}, ["id", "name", "cat", "yr", "v", "tags", "j", "ts"]),
        ({"ilike": "NUM_A"}, ["num_a"]),
        ({"glob": "num_*"}, ["num_a", "num_b"]),
        ({"similar_to": "num_."}, ["num_a", "num_b"]),
    ],
)
def test_star_patterns(db: duckdb.DuckDBPyConnection, kwargs: dict[str, str], expected: list[str]) -> None:
    assert names(select(star(**kwargs)).from_(T).execute(db)) == expected  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]


def test_star_pattern_with_exclude_and_table_star(db: duckdb.DuckDBPyConnection) -> None:
    q = select(table(T).star(exclude=["num_a"], like="num%")).from_(T)
    assert q.sql.startswith("""SELECT "t".* EXCLUDE ("num_a") LIKE 'num%'""")
    assert names(q.execute(db)) == ["num_b"]
    with pytest.raises(ValueError, match="RENAME"):
        star(like="a%", rename={"a": "b"})
    with pytest.raises(ValueError, match="at most one"):
        star(like="a%", glob="a*")


def test_struct_star(db: duckdb.DuckDBPyConnection) -> None:
    s = col("s", type_=qlt.Struct(a=qlt.Integer, b=qlt.Varchar))
    q = select(s.star()).from_(select(lit({"a": 1, "b": "x"}).as_("s")).subquery("q"))
    assert names(q.execute(db)) == ["a", "b"]


def test_columns_selectors(db: duckdb.DuckDBPyConnection) -> None:
    assert names(select(columns("num_.*")).from_(T).execute(db)) == ["num_a", "num_b"]
    assert names(select(columns(["id", "name"])).from_(T).execute(db)) == ["id", "name"]
    assert names(select(columns(lambda c: c.like("num%"))).from_(T).execute(db)) == ["num_a", "num_b"]
    assert len(names(select(columns(star(exclude=["name"]))).from_(T).execute(db))) == 9
    assert len(names(select(columns(T)).from_(T).execute(db))) == 10
    assert select(columns(T)).sql == 'SELECT COLUMNS("t".*)'


def test_columns_expressions_and_unpacking(db: duckdb.DuckDBPyConnection) -> None:
    assert select(fn.max(columns("num_.*"))).from_(T).execute(db).fetchall() == [(6, 7)]
    renamed = select(columns("num_(.*)").as_(r"x_\1")).from_(T)
    assert names(renamed.execute(db)) == ["x_a", "x_b"]
    unpacked = select(fn.coalesce(T.v, *columns("num_.*"))).from_(T).order_by(T.id)
    assert 'coalesce("t"."v", *COLUMNS(\'num_.*\'))' in unpacked.sql
    assert unpacked.execute(db).fetchall() == [(10,), (20,), (30,)]
    assert select().from_(T).where(columns(["num_a", "num_b"]) > 3).execute(db).fetchall()[0][0] == 2


def test_expression_is_not_iterable() -> None:
    with pytest.raises(TypeError, match="not iterable"):
        list(T.tags)


def test_positional_reference(db: duckdb.DuckDBPyConnection) -> None:
    assert select(positional(2)).from_(T).order_by(T.id).limit(1).execute(db).fetchall() == [("x",)]


# expressions ----------------------------------------------------------------------------------------------------------


def test_list_comprehension(db: duckdb.DuckDBPyConnection) -> None:
    q = select(list_comprehension(T.tags, lambda x: x * 2, where=lambda x: x > 1)).from_(T).order_by(T.id)
    assert '[("x" * ?) FOR "x" IN "t"."tags" IF ("x" > ?)]' in q.sql
    assert q.execute(db).fetchall() == [([4, 6],), ([8, 10],), ([],)]
    indexed = select(list_comprehension(T.tags, lambda x, i: x + i)).from_(T).order_by(T.id).limit(1)
    assert indexed.execute(db).fetchall() == [([2, 4, 6],)]


def test_slices_and_indexes(db: duckdb.DuckDBPyConnection) -> None:
    q = select(T.tags[1:3:2], T.tags[-1], T.name[1:1]).from_(T).where(T.id == 1)
    assert q.execute(db).fetchall() == [([1, 3], 3, "x")]


def test_json_and_list_operators(db: duckdb.DuckDBPyConnection) -> None:
    q = select(T.j.json_get("a"), T.j.json_get_text("$.a.b"), T.tags.has_all([1]), T.tags.has_any([5])).from_(T)
    assert q.order_by(T.id).execute(db).fetchall()[:2] == [('{"b":1}', "1", True, False), ('{"b":2}', "2", False, True)]
    assert select(T.id).from_(T).where(T.tags.contained_by([1, 2, 3, 4])).execute(db).fetchall() == [(1,), (3,)]


def test_any_all_try(db: duckdb.DuckDBPyConnection) -> None:
    assert select(T.id).from_(T).where(T.v > all_(select(lit(15)))).order_by(T.id).execute(db).fetchall() == [
        (2,),
        (3,),
    ]
    assert select(T.id).from_(T).where(T.id == any_(lit([1, 3]))).order_by(T.id).execute(db).fetchall() == [(1,), (3,)]
    assert select(try_(val("x").cast(qlt.Integer))).execute(db).fetchall() == [(None,)]


def test_boolean_tests_and_time_zone(db: duckdb.DuckDBPyConnection) -> None:
    assert select(T.id).from_(T).where((T.v > 15).is_true()).order_by(T.id).execute(db).fetchall() == [(2,), (3,)]
    assert "AT TIME ZONE" in T.ts.at_time_zone("UTC").sql


def test_window_frame_options(db: duckdb.DuckDBPyConnection) -> None:
    excl = fn.sum(T.v).over(order_by=T.id, frame=rows_between(None, None, exclude="current row"))
    assert "EXCLUDE CURRENT ROW" in excl.sql
    assert select(excl).from_(T).order_by(T.id).execute(db).fetchall() == [(50,), (40,), (30,)]
    days = fn.sum(T.v).over(order_by=T.ts, frame=range_between(-datetime.timedelta(days=1), 0))
    assert select(days).from_(T).order_by(T.id).execute(db).fetchall() == [(10,), (30,), (30,)]
    ordered = fn.first_value(T.v, order_by=T.id.desc(), ignore_nulls=True).over()
    assert 'first_value("t"."v" ORDER BY "t"."id" DESC IGNORE NULLS) OVER ()' in ordered.sql
    assert select(ordered).from_(T).execute(db).fetchall()[0] == (30,)


# FROM / SELECT --------------------------------------------------------------------------------------------------------


def test_values_source(db: duckdb.DuckDBPyConnection) -> None:
    v = values((1, "a"), (2, "b"), alias="v", columns=["k", "s"])
    q = select(v.c.s).from_(v).join(T, T.id == v.c.k).order_by(v.c.k)
    assert '(VALUES (?, ?), (?, ?)) AS "v"("k", "s")' in q.sql
    assert q.execute(db).fetchall() == [("a",), ("b",)]


def test_column_aliases(db: duckdb.DuckDBPyConnection) -> None:
    aliased = table("t").as_("q", ["c1", "c2"])
    assert select(aliased.c.c2).from_(aliased).order_by(aliased.c.c1).limit(1).execute(db).fetchall() == [("x",)]
    sub = select(T.id, T.name).from_(T).subquery("s", columns=["a", "b"])
    assert select(sub.c.b).from_(sub).where(sub.c.a == 2).execute(db).fetchall() == [("y",)]
    ordinal = fn.table.unnest(["p", "q"]).as_("u", ["x", "i"]).with_ordinality()
    assert select().from_(ordinal).execute(db).fetchall() == [("p", 1), ("q", 2)]


def test_file_source(db: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    path = (tmp_path / "t.parquet").as_posix()
    copy_to(T, path, format="parquet").execute(db)
    f = file(path).as_("f")
    assert select(fn.count()).from_(f).execute(db).fetchall() == [(3,)]
    assert select(f.c.name).from_(f).where(f.c.id == 2).execute(db).fetchall() == [("y",)]


def test_tablesample_and_limit_percent(db: duckdb.DuckDBPyConnection) -> None:
    q = select(fn.count()).from_(tablesample(T, rows=2, method="reservoir", seed=1))
    assert q.sql == 'SELECT count(*) FROM "t" TABLESAMPLE reservoir(2 ROWS) REPEATABLE (1)'
    assert q.execute(db).fetchall() == [(2,)]
    assert "TABLESAMPLE 50 PERCENT" in select().from_(table("t").tablesample(percent=50)).sql
    lim = select(T.id).from_(T).order_by(T.id).limit(50, percent=True)
    assert lim.sql.endswith("LIMIT ?%")
    assert lim.execute(db).fetchall() == [(1,)]


def test_recursive_cte_using_key(db: duckdb.DuckDBPyConnection) -> None:
    r = table("r")
    body = select(lit(1).as_("k"), lit(1).as_("n")).union(select(r.c.k, r.c.n + 1).from_(r).where(r.c.n < 3))
    cte = body.cte("r", columns=["k", "n"], using_key=["k"])
    q = select().with_recursive(cte).from_(cte)
    assert 'WITH RECURSIVE "r" ("k", "n") USING KEY ("k") AS (' in q.sql
    assert q.execute(db).fetchall() == [(1, 3)]


def test_pivot(db: duckdb.DuckDBPyConnection) -> None:
    p = pivot(T).on(T.cat, values=["a", "b"]).using(fn.sum(T.v).as_("total")).group_by(T.yr).order_by(T.yr)
    assert p.sql == ('PIVOT "t" ON "cat" IN (?, ?) USING sum("v") AS "total" GROUP BY "yr" ORDER BY "yr"')
    cur = p.execute(db)
    assert names(cur) == ["yr", "a_total", "b_total"]
    assert cur.fetchall() == [(2025, 10, None), (2026, 30, 20)]


def test_pivot_as_subquery_falls_back_to_literals(db: duckdb.DuckDBPyConnection) -> None:
    p = pivot(T).on(T.cat).using(fn.sum(T.v)).group_by(T.yr).subquery("p")
    q = select(p.c.yr, p.c.a).from_(p).where(p.c.yr > 2025)
    assert q.params == (2025,)  # DuckDB rejects parameters here; execute() retries with literals
    assert q.execute(db).fetchall() == [(2026, 30)]
    assert "> 2025" in q.sql_inline


def test_unpivot(db: duckdb.DuckDBPyConnection) -> None:
    u = unpivot(select(T.id, T.num_a, T.num_b).from_(T)).on(columns("num_.*")).into(name="col", value="val")
    assert u.sql.endswith("""ON COLUMNS('num_.*') INTO NAME "col" VALUE "val\"""")
    rows = u.order_by("id", "col").execute(db).fetchall()
    assert rows[:2] == [(1, "num_a", 2), (1, "num_b", 3)]


# DML ------------------------------------------------------------------------------------------------------------------


def test_merge(db: duckdb.DuckDBPyConnection) -> None:
    staged = values((1, "updated"), (9, "new"), alias="s", columns=["id", "name"])
    q = (
        merge_into(T)
        .using(staged, on=T.id == staged.c.id)
        .when_matched(staged.c.name != "skip")
        .update(name=staged.c.name)
        .when_not_matched()
        .insert({"id": staged.c.id, "name": staged.c.name})
        .returning(merge_action, T.id)
    )
    assert q.sql.startswith('MERGE INTO "t" USING (VALUES')
    assert sorted(q.execute(db).fetchall()) == [("INSERT", 9), ("UPDATE", 1)]
    assert select(T.name).from_(T).where(T.id == 1).execute(db).fetchall() == [("updated",)]


def test_merge_variants(db: duckdb.DuckDBPyConnection) -> None:
    src = select(T.id, T.name).from_(T).where(T.id == 2).subquery("s")
    merge_into(T).using(src, columns="id").when_matched().delete().when_not_matched().insert_by_name().execute(db)
    assert select(fn.count()).from_(T).execute(db).fetchall() == [(2,)]
    q = merge_into(T).using(T, columns="id").when_not_matched_by_source(T.id > 100).delete()
    assert " WHEN NOT MATCHED BY SOURCE AND " in q.sql
    q.execute(db)
    err = merge_into(T).using(T, columns="id").when_matched().error("boom")
    with pytest.raises(duckdb.Error, match="boom"):
        err.execute(db)


def test_insert_by_position_and_truncate(db: duckdb.DuckDBPyConnection) -> None:
    assert insert(T).by_position().select(select().from_(T).limit(0)).sql.startswith('INSERT INTO "t" BY POSITION')
    truncate(T).execute(db)
    assert select(fn.count()).from_(T).execute(db).fetchall() == [(0,)]


def test_copy(db: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    out = (tmp_path / "o.csv").as_posix()
    q = copy_to(select(T.id, T.name).from_(T).where(T.id < 3), out, format="csv", header=True, delimiter="|")
    assert "TO '" in q.sql
    assert "(FORMAT 'csv', HEADER true, DELIMITER '|')" in q.sql
    q.execute(db)
    db.execute("CREATE TABLE back (id INTEGER, name VARCHAR)")
    copy_from("back", out, header=True, delimiter="|").execute(db)
    assert db.execute("SELECT * FROM back ORDER BY id").fetchall() == [(1, "x"), (2, "y")]
    parts = (tmp_path / "parts").as_posix()
    copy_to(T, parts, format="parquet", partition_by=["yr"]).execute(db)
    assert sorted(p.name for p in (tmp_path / "parts").iterdir()) == ["yr=2025", "yr=2026"]


# DDL ------------------------------------------------------------------------------------------------------------------


def test_create_view_inlines_values(db: duckdb.DuckDBPyConnection) -> None:
    v = create_view("big", select(T.id).from_(T).where(T.v > 15), columns=["ident"], or_replace=True)
    assert v.sql == 'CREATE OR REPLACE VIEW "big" ("ident") AS SELECT "t"."id" FROM "t" WHERE ("t"."v" > 15)'
    v.execute(db)
    assert db.execute("SELECT * FROM big ORDER BY 1").fetchall() == [(2,), (3,)]
    drop_view("big", if_exists=True).execute(db)


def test_schema_sequence_index_type(db: duckdb.DuckDBPyConnection) -> None:
    create_schema("sc", if_not_exists=True).execute(db)
    create_sequence(("sc", "seq"), start=10, increment=5).execute(db)
    assert select(fn.nextval("sc.seq"), fn.nextval("sc.seq")).execute(db).fetchall() == [(10, 15)]
    idx = create_index("ix", T, T.name, fn.lower(T.name), unique=False, if_not_exists=True)
    assert idx.sql == 'CREATE INDEX IF NOT EXISTS "ix" ON "t" ("name", (lower("name")))'
    idx.execute(db)
    create_type("mood", qlt.Enum("sad", "ok")).execute(db)
    assert db.execute("SELECT 'ok'::mood").fetchall() == [("ok",)]


def test_macros(db: duckdb.DuckDBPyConnection) -> None:
    m = create_macro("add2", lambda a, b=2: a + b, or_replace=True)
    assert m.sql == 'CREATE OR REPLACE MACRO "add2"("a", "b" := 2) AS ("a" + "b")'
    m.execute(db)
    assert select(func.add2(1), func.add2(1, 5)).execute(db).fetchall() == [(3, 6)]
    create_macro("first_n", lambda n: select().from_(fn.table.range(n))).execute(db)
    assert select().from_(func.first_n(2)).execute(db).fetchall() == [(0,), (1,)]
    create_macro("ov", lambda a: a, lambda a, b: a * b).execute(db)
    assert select(func.ov(3), func.ov(3, 4)).execute(db).fetchall() == [(3, 12)]
    drop_macro("first_n", table=True).execute(db)


def test_alter_table(db: duckdb.DuckDBPyConnection) -> None:
    alt = alter_table(T)
    alt.add_column("extra", qlt.Integer, default=7, if_not_exists=True).execute(db)
    assert select(col("extra")).from_(T).limit(1).execute(db).fetchall() == [(7,)]
    alt.rename_column("extra", "more").execute(db)
    alt.alter_type("more", qlt.BigInt, using=col("more") * 2).execute(db)
    assert select(col("more")).from_(T).limit(1).execute(db).fetchall() == [(14,)]
    alt.set_default("more", 1).execute(db)
    alt.drop_default("more").execute(db)
    alt.drop_column("more", if_exists=True).execute(db)
    db.execute("CREATE TABLE r1 (a INTEGER)")
    alter_table("r1").rename_to("r2").execute(db)
    alter_table("r2").add_primary_key("a").execute(db)
    drop_table("r2", if_exists=True, cascade=True).execute(db)


def test_comments(db: duckdb.DuckDBPyConnection) -> None:
    comment_on_table(T, "main table").execute(db)
    comment_on_column(T.id, "it's the key").execute(db)
    assert db.execute("SELECT comment FROM duckdb_tables() WHERE table_name = 't'").fetchall() == [("main table",)]
    assert db.execute("SELECT comment FROM duckdb_columns() WHERE column_name = 'id'").fetchall() == [("it's the key",)]


# utilities ------------------------------------------------------------------------------------------------------------


def test_introspection(db: duckdb.DuckDBPyConnection) -> None:
    assert describe(T).execute(db).fetchall()[0][:2] == ("id", "INTEGER")
    assert describe(select(T.v.cast(qlt.BigInt).as_("x")).from_(T)).execute(db).fetchall()[0][:2] == ("x", "BIGINT")
    assert summarize(T).execute(db).fetchall()[0][0] == "id"
    assert ("t",) in show_tables().execute(db).fetchall()


def test_attach_use_settings(db: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    path = (tmp_path / "other.db").as_posix()
    attach(path, "other", read_only=False).execute(db)
    use("other").execute(db)
    db.execute("CREATE TABLE here (x INTEGER)")
    use("memory").execute(db)
    assert db.execute("SELECT count(*) FROM other.here").fetchall() == [(0,)]
    detach("other", if_exists=True).execute(db)
    set_("threads", 2).execute(db)
    assert db.execute("SELECT current_setting('threads')").fetchall() == [(2,)]
    set_variable("limit_v", 25).execute(db)
    assert select(T.id).from_(T).where(T.v > fn.getvariable("limit_v")).execute(db).fetchall() == [(3,)]
    assert pragma("table_info", "t").execute(db).fetchall()[0][1] == "id"


def test_attach_with_type(db: duckdb.DuckDBPyConnection, tmp_path: Path) -> None:
    path = (tmp_path / "typed.db").as_posix()
    stmt = attach(path, "typed", type="duckdb", if_not_exists=True)
    assert stmt.sql == f"ATTACH IF NOT EXISTS '{path}' AS \"typed\" (TYPE duckdb)"
    stmt.execute(db)
    assert ("typed",) in [(r[0],) for r in show_databases().execute(db).fetchall()]
    detach("typed").execute(db)
    with pytest.raises(ValueError, match="Invalid"):
        attach(path, type="duckdb); DROP TABLE t")


def test_create_secret(db: duckdb.DuckDBPyConnection) -> None:
    stmt = create_secret("s", type="s3", key_id="AKIA", secret="x'y", region="ap-northeast-1")
    assert stmt.sql == "CREATE SECRET \"s\" (TYPE s3, KEY_ID 'AKIA', SECRET 'x''y', REGION 'ap-northeast-1')"
    stmt.execute(db)
    assert db.execute("SELECT name, type FROM duckdb_secrets()").fetchall() == [("s", "s3")]
    drop_secret("s").execute(db)
    assert create_secret(type="s3", persistent=True, storage="local_file").sql == (
        'CREATE PERSISTENT SECRET IN "local_file" (TYPE s3)'
    )
    with pytest.raises(ValueError, match="Invalid secret type"):
        create_secret("s", type="s3) (x")


def test_from_first_with_new_sources(db: duckdb.DuckDBPyConnection) -> None:
    assert from_(values((1,), (2,), alias="v", columns=["n"])).execute(db).fetchall() == [(1,), (2,)]
