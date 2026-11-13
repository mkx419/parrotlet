# ファイルの読み書き

DuckDB は、Parquet・CSV・JSON などのファイルを直接読み書きできます。parrotlet では、次の方法を使います。

| やりたいこと | 方法 |
|---|---|
| ファイルをテーブルのようにクエリする | `file(path)`、`fn.table.read_parquet(...)` など |
| ファイルの内容をテーブルに入れる | `copy_from()`、`insert(...).select(...)`、`create_table(...).as_(...)` |
| テーブルやクエリの結果をファイルに書く | `copy_to()` |
| データベース全体を書き出す・読み込む | `export_database()` / `import_database()` |

パスを取る引数には、文字列のほかに `pathlib.Path` も渡せます。対象は、`file()`、`copy_to()`、`copy_from()`、`export_database()`、`import_database()` と、`fn.table.read_parquet()` や `fn.table.glob()` などのファイルを読むテーブル関数です。`Path` は、区切り文字を `/` にした文字列として DuckDB に渡されます。

## ファイルをクエリする

### パスを直接書く

```python
from parrotlet import file

select().from_(file("data/*.parquet"))  # SELECT * FROM 'data/*.parquet'

logs = file("logs/2026-*.csv").as_("logs")
select(logs.c.level, fn.count()).from_(logs).group_by(logs.c.level)
# SELECT "logs"."level", count(*) FROM 'logs/2026-*.csv' AS "logs"
#   GROUP BY "logs"."level"
```

ファイルの形式は拡張子から判定されます。グロブ（`*`、`**`）で複数のファイルをまとめて読めます。カラムを参照するには `.as_("別名")` を付けます。

### 読み込み関数を使う

読み込みのオプションを指定するときは、テーブル関数（`fn.table`）を使います。

```python
p = fn.table.read_parquet("data/*.parquet", hive_partitioning=True, union_by_name=True)
select().from_(p.as_("p"))
# SELECT * FROM
#   read_parquet(?, "hive_partitioning" := ?, "union_by_name" := ?) AS "p"

select().from_(
    fn.table.read_csv(
        "x.csv",
        header=True,
        delim="|",
        columns={"id": "INTEGER", "name": "VARCHAR"},
    )
)
# SELECT * FROM read_csv(?, "header" := ?, "delim" := ?, "columns" := ?)

select().from_(fn.table.read_json("events.jsonl", format="newline_delimited"))
```

| 関数 | 形式 |
|---|---|
| `fn.table.read_parquet` | Parquet |
| `fn.table.read_csv` | CSV |
| `fn.table.read_json` / `fn.table.read_json_auto` | JSON / JSON Lines |
| `fn.table.read_text` / `fn.table.read_blob` | テキスト / バイナリのファイルを1行1ファイルで |
| `fn.table.glob` | パターンに一致するファイル名の一覧 |
| `fn.table.parquet_metadata` / `fn.table.parquet_schema` | Parquet のメタデータ |

オプションは DuckDB の関数の名前付き引数と同じ名前で、キーワード引数として渡します。パスやオプションの値はパラメータとして渡されます。

S3 や HTTP のファイルは、httpfs 拡張を読み込み、必要なら[シークレット](ddl.md#secrets)を作ってから、URL を指定して読みます。

```python
db = Database(extensions=["httpfs"])
db.select(fn.count()).from_(file("s3://bucket/data/*.parquet")).fetchone()
```

## ファイルからテーブルに入れる

### COPY FROM

既存のテーブルに、ファイルの内容を入れます。

```python
from parrotlet import copy_from

copy_from(User, "users.csv", header=True)
# COPY "users" FROM 'users.csv' (HEADER true)

copy_from(User, "users.csv", [User.id, User.name], format="csv")
# COPY "users" ("id", "name") FROM 'users.csv' (FORMAT 'csv')
```

第3引数でカラムを指定すると、そのカラムだけに値を入れます（残りは既定値）。

### INSERT ... SELECT / CREATE TABLE AS

変換しながら入れたいときは、SELECT と組み合わせます。

```python
src = fn.table.read_csv("users.csv", header=True).as_("src")
cleaned = select(src.c.id, fn.trim(src.c.name).as_("name")).from_(src)
insert(User).by_name().select(cleaned)

create_table("raw_events").as_(select().from_(file("events/*.parquet")))
# CREATE TABLE "raw_events" AS SELECT * FROM 'events/*.parquet'
```

## ファイルに書き出す

### COPY TO

テーブルかクエリの結果を、ファイルに書き出します。

```python
from parrotlet import copy_to

copy_to(
    select(User.id, User.name).from_(User),
    "out.parquet",
    format="parquet",
    compression="zstd",
)
# COPY (SELECT "users"."id", "users"."name" FROM "users")
#   TO 'out.parquet' (FORMAT 'parquet', COMPRESSION 'zstd')

copy_to(User, "users.csv", header=True, delimiter="|")
# COPY "users" TO 'users.csv' (HEADER true, DELIMITER '|')

copy_to(
    User,
    "users",
    format="parquet",
    partition_by=["country"],
    overwrite_or_ignore=True,
)
# COPY "users" TO 'users'
#   (FORMAT 'parquet', PARTITION_BY ("country"), OVERWRITE_OR_IGNORE true)
```

オプションには、DuckDB の COPY のオプションをキーワード引数で指定します。名前は大文字に変換されます。

| オプションの値 | 出力される SQL |
|---|---|
| 文字列・数値・真偽値 | リテラル（`'parquet'`、`true`） |
| 文字列のリスト | カラム名のリスト（`partition_by=["year", "month"]` → `("year", "month")`） |
| 式 | リテラルとして展開した式 |
| `None` | オプションを省略 |

よく使うオプションは次のとおりです。

| オプション | 意味 |
|---|---|
| `format` | `"parquet"` / `"csv"` / `"json"` |
| `header` / `delimiter` | CSV のヘッダーと区切り文字 |
| `compression` | `"zstd"`、`"snappy"`、`"gzip"` など |
| `partition_by` | Hive 形式のパーティションに分けて書く |
| `overwrite_or_ignore` / `overwrite` | 出力先が存在するときの動作 |
| `per_thread_output` | スレッドごとにファイルを分ける |

## データベース全体 {#whole-database}

```python
from parrotlet import copy_database, export_database, import_database

export_database("backup", format="parquet", compression="zstd")
# EXPORT DATABASE 'backup' (FORMAT 'parquet', COMPRESSION 'zstd')

import_database("backup")  # IMPORT DATABASE 'backup'

copy_database("memory", "backup", schema_only=True)
# COPY FROM DATABASE "memory" TO "backup" (SCHEMA)
```

`copy_database()` は、ATTACH した2つのデータベースの間で、すべてのオブジェクトをコピーします。`schema_only=True` はテーブル定義だけ、`data_only=True` はデータだけをコピーします。

## pandas / polars / Arrow

DataFrame や Arrow のテーブルは、DuckDB の接続に名前を付けて登録してから、テーブル名として参照します。

```python
import pandas as pd

df = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
db.connection.register("df_users", df)

db.select(fn.count()).from_("df_users").fetchone()  # (2,)
db.insert(User).by_name().select(select().from_("df_users")).execute()
db.connection.unregister("df_users")
```

!!! note "変数名の自動参照は使えない"
    DuckDB の Python API には、`FROM df` のように Python の変数名を直接参照できる機能（replacement scan）があります。しかし、parrotlet 経由で実行すると、DuckDB は呼び出し元の変数を見つけられません。`register()` で登録してください。

結果を DataFrame で受け取るには `.df()`（pandas）や `.pl()`（polars）を使います。
