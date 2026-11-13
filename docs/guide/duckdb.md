# DuckDB 固有の機能

DuckDB が標準 SQL に加えている構文と、ユーティリティ文の書き方です。

## star の修飾子 {#star}

```python
from parrotlet import star

star(exclude=["tags"])  # * EXCLUDE ("tags")
star(rename={"id": "user_id"})  # * RENAME ("id" AS "user_id")
star(replace={"name": fn.upper(User.name)})
# * REPLACE (upper("users"."name") AS "name")

star(like="num_%")  # * LIKE 'num_%'
star(exclude=["a"], glob="n*")  # * EXCLUDE ("a") GLOB 'n*'
table(User).star(exclude=["tags"])  # "users".* EXCLUDE ("tags")
col("s", type_=qlt.Struct(a=qlt.Integer)).star()  # "s".*（構造体をカラムに展開）
```

| 引数 | SQL | 意味 |
|---|---|---|
| `exclude=[...]` | `EXCLUDE (...)` | 指定したカラムを除く |
| `replace={name: expr}` | `REPLACE (expr AS name)` | カラムの値を式で置き換える |
| `rename={old: new}` | `RENAME (old AS new)` | カラム名を変える |
| `like` / `not_like` / `ilike` / `not_ilike` / `glob` / `similar_to` | `LIKE '...'` など | 名前がパターンに一致するカラムだけを残す |

- パターンは1つだけ指定できます。
- DuckDB の制約により、パターンと `rename` は併用できません（`ValueError`）。
- パターンはリテラルとして埋め込まれます。

## COLUMNS(...)

`COLUMNS(...)` は、複数のカラムに同じ式を適用します。

```python
from parrotlet import columns

columns("num_.*")  # COLUMNS('num_.*')：正規表現
columns(["id", "name"])  # COLUMNS(['id', 'name'])：カラム名のリスト
columns(star(exclude=["name"]))  # COLUMNS(* EXCLUDE ("name"))
columns(User)  # COLUMNS("users".*)

# カラム名に対するラムダ
columns(lambda c: c.like("num_%"))  # COLUMNS(lambda "c": ("c" LIKE ?))
```

```python
# 各カラムの最大値
select(fn.max(columns("num_.*"))).from_("t")
# SELECT max(COLUMNS('num_.*')) FROM "t"

# 正規表現のグループで別名を付ける
select(columns("num_(.*)").as_(r"x_\1")).from_("t")

# 引数として展開
select(fn.coalesce(*columns("num_.*"))).from_("t")
# coalesce(*COLUMNS('num_.*'))

# すべてのカラムで AND
select().from_("t").where(columns(["a", "b"]) > 0)
# WHERE (COLUMNS([...]) > ?)
```

`COLUMNS(...)` は型なしの式です。

## FROM 先頭構文

```python
from parrotlet import from_

from_(User)  # SELECT * FROM "users"
from_(User).where(User.age > 20).select(User.name)
db.from_(User).fetch_as(User)
```

## その他の構文

| 機能 | 書き方 | 説明のあるページ |
|---|---|---|
| GROUP BY ALL / ORDER BY ALL | `.group_by_all()`、`.order_by_all()` | [SELECT](select.md) |
| DISTINCT ON | `.distinct(on=...)` | [SELECT](select.md#distinct) |
| QUALIFY | `.qualify(fn.row_number().over(...) == 1)` | [集約とウィンドウ関数](aggregates.md#qualify) |
| ASOF / POSITIONAL / SEMI / ANTI JOIN | `.asof_join(t, cond)` など | [SELECT](select.md#join) |
| USING SAMPLE / TABLESAMPLE | `.using_sample(percent=10)`、`tablesample(T, rows=100)` | [SELECT](select.md#using-sample) |
| LIMIT n% | `.limit(10, percent=True)` | [SELECT](select.md) |
| UNION BY NAME | `q1.union(q2, by_name=True)` | [SELECT](select.md#set-operations) |
| 再帰 CTE の USING KEY | `q.cte("r", using_key=["k"])` | [テーブルと FROM ソース](sources.md#cte) |
| ファイルの直接読み込み | `file("data/*.parquet")` | [ファイルの読み書き](files.md) |
| VALUES をテーブルとして使う | `values(..., alias="v", columns=[...])` | [テーブルと FROM ソース](sources.md#values) |
| WITH ORDINALITY | `fn.table.unnest(xs).as_("u", ["x"]).with_ordinality()` | [テーブルと FROM ソース](sources.md#table-functions) |
| PIVOT / UNPIVOT | `pivot(...)`、`unpivot(...)` | [SELECT](select.md#pivot-unpivot) |
| MERGE | `merge_into(...)` | [DML](dml.md#merge) |
| INSERT OR REPLACE / BY NAME | `.or_replace()`、`.by_name()` | [DML](dml.md#insert) |
| リスト内包表記・ラムダ | `list_comprehension(...)`、`fn.list_transform(xs, lambda x: ...)` | [式](expressions.md#lambdas) |
| JSON・リストの演算子 | `.json_get()`、`.has_all()` など | [式](expressions.md) |
| スライスのステップ・負のインデックス | `xs[1:5:2]`、`xs[-1]` | [式](expressions.md#nested) |
| `#n` | `positional(1)` | [式](expressions.md#misc) |
| TRY | `try_(expr)` | [式](expressions.md#misc) |
| マクロ | `create_macro("f", lambda a, b=1: a + b)` | [DDL](ddl.md#macros) |

## ユーティリティ文 {#utility}

どれもステートメントを返すので、`db.execute(...)` で実行します。結果を返す文（`describe` など）は `db.execute(...).fetchall()` や `db.bind(...).fetchall()` で受け取ります。

```python
db.bind(describe(User)).fetchall()
# [('id', 'BIGINT', 'NO', 'PRI', None, None), ...]
db.execute(set_("threads", 4))
```

### 調べる

| 関数 | SQL |
|---|---|
| `describe(User)` / `describe(query)` | `DESCRIBE "users"` / `DESCRIBE SELECT ...`（カラム名と型） |
| `summarize(User)` / `summarize(query)` | `SUMMARIZE ...`（カラムごとの統計） |
| `show_tables()` / `show_tables(all=True)` / `show_tables(database="other")` | `SHOW TABLES` / `SHOW ALL TABLES` / `SHOW TABLES FROM "other"` |
| `show_databases()` | `SHOW DATABASES` |
| `explain(q)` / `explain(q, analyze=True)` | `EXPLAIN ...` / `EXPLAIN ANALYZE ...` |
| `pragma("table_info", "users")` | `PRAGMA table_info('users')` |
| `call(func.pragma_table_info("users"))` | `CALL pragma_table_info(?)` |

### データベース

| 関数 | SQL |
|---|---|
| `attach("other.duckdb", "other", read_only=True)` | `ATTACH 'other.duckdb' AS "other" (READ_ONLY true)` |
| `attach(path, alias, type="postgres", if_not_exists=True, **options)`（`path` は `str` か `pathlib.Path`） | 他の形式のデータベースを ATTACH |
| `detach("other", if_exists=True)` | `DETACH IF EXISTS "other"` |
| `use("other")` / `use(("other", "main"))` | `USE "other"` / `USE "other"."main"` |
| `checkpoint()` / `checkpoint("other", force=True)` | `CHECKPOINT` / `FORCE CHECKPOINT "other"` |
| `vacuum(User, analyze=True)` | `VACUUM ANALYZE "users"` |
| `analyze()` / `analyze(User)` | `ANALYZE` |
| `export_database(path, **options)` / `import_database(path)` | [ファイルの読み書き](files.md#whole-database) |

ATTACH したデータベースのテーブルは、`table("t", catalog="other")` や、`class T(Model, schema=...)` で参照します。

```python
attach("dbname=shop host=localhost", "pg", type="postgres", read_only=True)
# ATTACH 'dbname=shop host=localhost' AS "pg" (TYPE postgres, READ_ONLY true)
```

### 設定と変数

| 関数 | SQL |
|---|---|
| `set_("threads", 4)` | `SET threads = 4` |
| `set_("memory_limit", "4GB", scope="global")` | `SET GLOBAL memory_limit = '4GB'`（`scope` は `"global"` / `"session"` / `"local"`） |
| `reset("threads")` | `RESET threads` |
| `pragma("threads", value=4)` | `PRAGMA threads = 4` |
| `set_variable("cutoff", 100)` | `SET VARIABLE "cutoff" = 100`（`fn.getvariable("cutoff")` で参照） |
| `reset_variable("cutoff")` | `RESET VARIABLE "cutoff"` |

設定名・PRAGMA 名・拡張機能名は、識別子として正しいかを検査してから埋め込まれます。

### 拡張機能

| 関数 | SQL |
|---|---|
| `install("spatial")` | `INSTALL spatial` |
| `install("h3", from_="community")` | `INSTALL h3 FROM community` |
| `install("spatial", force=True)` | `FORCE INSTALL spatial` |
| `load("spatial")` | `LOAD spatial` |

parrotlet は、型付きの関数や型が必要とする拡張機能を自動で読み込みます（[Database](database.md#extensions)）。

### トランザクション

| 関数 | SQL |
|---|---|
| `begin()` | `BEGIN TRANSACTION` |
| `commit()` | `COMMIT` |
| `rollback()` | `ROLLBACK` |

使い方は [Database](database.md#transactions) を参照してください。

## パラメータとリテラル

- 値は通常 `?` パラメータとして DuckDB に渡されます。
- DuckDB がパラメータを受け付けない場所では、エスケープ済みのリテラルとして埋め込まれます。対象は、DDL、マクロ、COPY などのオプション、star のパターン、`COLUMNS('...')`、リストのインデックス、構造体のキー、ファイルのパスです。
- 実行して初めてパラメータが使えないと分かる文もあります（IN リストのない PIVOT をサブクエリにした場合など）。このときは値をリテラルとして埋め込み、1回だけ自動で再実行します。
- `q.sql_inline` で、値をリテラルとして埋め込んだ SQL を確認できます。
