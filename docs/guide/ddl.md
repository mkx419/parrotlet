# DDL

テーブルやビューなど、データベースのオブジェクトを作成・変更・削除するステートメントです。

DuckDB の DDL はパラメータを受け付けないため、DDL に含まれる値（既定値、CHECK の条件、ビューの中の値など）は、エスケープ済みのリテラルとして埋め込まれます。

```python
db.execute(create_view("adults", select(User).from_(User).where(User.age >= 20)))
# CREATE VIEW "adults" AS SELECT "users".* FROM "users" WHERE ("users"."age" >= 20)
```

DDL の関数は、どの `Database` にもバインドされていないステートメントを返します。`db.execute(stmt)` で実行するか、`stmt.execute(con)` に接続を渡してください。

## オブジェクトの名前

名前を取る引数には、次の形式を使えます。

| 形式 | SQL |
|---|---|
| `"name"` | `"name"` |
| `("schema", "name")` | `"schema"."name"` |
| `("catalog", "schema", "name")` | `"catalog"."schema"."name"` |

テーブルを取る引数（`drop_table`、`alter_table`、`comment_on_table` など）には、モデルのクラスや `table(...)` も渡せます。

## テーブル

テーブルの作成は[モデル](models.md#create-table)を参照してください（`create_table(Model)`、`db.register`）。

### ALTER TABLE {#alter-table}

`alter_table(T).<操作>(...)` は、それぞれ1つの ALTER TABLE 文になります（DuckDB は1つの文で1つの操作しかできません）。

```python
from parrotlet import alter_table

alter_table(User).add_column("score", qlt.Integer, default=0, if_not_exists=True)
# ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "score" INTEGER DEFAULT 0
```

| メソッド | SQL |
|---|---|
| `.add_column(name, type_, *, default=..., if_not_exists=False)` | `ADD COLUMN [IF NOT EXISTS] name type [DEFAULT ...]` |
| `.drop_column(name, *, if_exists=False, cascade=False)` | `DROP COLUMN [IF EXISTS] name [CASCADE]` |
| `.rename_column(old, new)` | `RENAME COLUMN old TO new` |
| `.rename_to(new)` | `RENAME TO new` |
| `.alter_type(column, type_, *, using=None)` | `ALTER COLUMN c TYPE t [USING expr]` |
| `.set_default(column, value)` | `ALTER COLUMN c SET DEFAULT value` |
| `.drop_default(column)` | `ALTER COLUMN c DROP DEFAULT` |
| `.set_not_null(column)` | `ALTER COLUMN c SET NOT NULL` |
| `.drop_not_null(column)` | `ALTER COLUMN c DROP NOT NULL` |
| `.add_primary_key(*columns)` | `ADD PRIMARY KEY (columns)` |

カラムは、名前の文字列か `User.age` などのカラムで指定します。

```python
alter_table(User).rename_column(User.age, "years")  # RENAME COLUMN "age" TO "years"
alter_table(User).alter_type("score", qlt.BigInt, using=col("score") * 10)
# ALTER TABLE "users" ALTER COLUMN "score" TYPE BIGINT USING ("score" * 10)
```

!!! note "モデルの定義は自動で変わらない"
    ALTER TABLE を実行しても、Python のモデルのクラスは変わりません。テーブルの変更に合わせて、モデルのカラムも書き換えてください。

### DROP / TRUNCATE / COMMENT

```python
from parrotlet import comment_on_column, comment_on_table, drop_table, truncate

drop_table(User, if_exists=True, cascade=True)
# DROP TABLE IF EXISTS "users" CASCADE

truncate(User)
# TRUNCATE "users"

comment_on_table(User, "registered users")
# COMMENT ON TABLE "users" IS 'registered users'

comment_on_column(User.name, "display name")
# COMMENT ON COLUMN "users"."name" IS 'display name'

comment_on_table(User, None)  # コメントを削除（IS NULL）
```

`comment_on_column()` には、テーブルで修飾されたカラム（`User.name` や `table("t").c.x`）を渡します。

## ビュー

```python
from parrotlet import alter_view_rename, create_view, drop_view

adults = select(User).from_(User).where(User.age >= 20)
create_view("adults", adults, or_replace=True)
# CREATE OR REPLACE VIEW "adults" AS
#   SELECT "users".* FROM "users" WHERE ("users"."age" >= 20)

create_view(
    ("analytics", "v"),
    select(User.id).from_(User),
    columns=["uid"],
    temporary=True,
)
# CREATE TEMPORARY VIEW "analytics"."v" ("uid") AS SELECT "users"."id" FROM "users"

alter_view_rename("adults", "grownups")  # ALTER VIEW "adults" RENAME TO "grownups"
drop_view("adults", if_exists=True)
```

| `create_view()` の引数 | 意味 |
|---|---|
| `columns` | ビューのカラム名 |
| `or_replace` / `if_not_exists` | 既存のビューの扱い（同時には指定できない） |
| `temporary` | 一時ビュー |

ビューをクエリで使うときは、`table("adults")` で参照します。

## スキーマ

```python
from parrotlet import create_schema, drop_schema

create_schema("analytics", if_not_exists=True)
# CREATE SCHEMA IF NOT EXISTS "analytics"

drop_schema("analytics", if_exists=True, cascade=True)
```

モデルをスキーマに置くときは `class T(Model, schema="analytics")` と書きます。

## シーケンス

```python
from parrotlet import create_sequence, drop_sequence

create_sequence("user_ids", start=100, increment=1, maxvalue=999, cycle=True)
# CREATE SEQUENCE "user_ids" START 100 INCREMENT BY 1 MAXVALUE 999 CYCLE
```

| 引数 | SQL |
|---|---|
| `start` / `increment` | `START n` / `INCREMENT BY n` |
| `minvalue` / `maxvalue` | `MINVALUE n` / `MAXVALUE n` |
| `cycle` | `CYCLE`（最大値のあと最小値に戻る） |
| `or_replace` / `temporary` / `if_not_exists` | 作成のオプション |

シーケンスの値は `fn.nextval("user_ids")` / `fn.currval("user_ids")` で取得します。モデルのカラムの既定値にすると、自動採番のカラムになります。

```python
class Ticket(Model):
    id: Column[int] = column(primary_key=True, default=fn.nextval("ticket_ids"))
    title: Column[str]


db.execute(create_sequence("ticket_ids", if_not_exists=True))
db.register(Ticket)
db.insert(Ticket).values(Ticket(title="a")).returning(Ticket.id).fetchall()
# [(1,)]
```

## インデックス

```python
from parrotlet import create_index, drop_index

create_index(
    "ix_users_name",
    User,
    User.name,
    fn.lower(User.name),
    unique=True,
    if_not_exists=True,
)
# CREATE UNIQUE INDEX IF NOT EXISTS "ix_users_name"
#   ON "users" ("name", (lower("name")))

drop_index("ix_users_name", if_exists=True)
```

カラムには、カラム名の文字列、モデルのカラム、式を渡せます。式は括弧で囲まれます。

## 型

```python
from parrotlet import create_type, drop_type

create_type("mood", qlt.Enum("sad", "ok", "happy"))
# CREATE TYPE "mood" AS ENUM('sad', 'ok', 'happy')

create_type("point", qlt.Struct(x=qlt.Double, y=qlt.Double), or_replace=True)
drop_type("mood", if_exists=True)
```

## マクロ {#macros}

Python のラムダから `CREATE MACRO` を作ります。ラムダの引数がマクロの引数に、Python の既定値が `name := value` になります。

```python
from parrotlet import create_macro, drop_macro, func

create_macro("add", lambda a, b=1: a + b)
# CREATE MACRO "add"("a", "b" := 1) AS ("a" + "b")

# 本体がステートメントならテーブルマクロ
create_macro("first_n", lambda n: select().from_(fn.table.range(n)))
# CREATE MACRO "first_n"("n") AS TABLE SELECT * FROM range("n")

# 引数の数によるオーバーロード
create_macro("f", lambda a: a, lambda a, b: a * b, or_replace=True)
# CREATE OR REPLACE MACRO "f"("a") AS "a", ("a", "b") AS ("a" * "b")
```

- ラムダの引数は、型なしのカラム参照（`ColumnRef[Any]`）として渡されます。
- 値はリテラルとして埋め込まれます。
- オーバーロードは、すべてスカラーマクロか、すべてテーブルマクロでなければなりません。

作ったマクロは `func.<名前>` で呼びます。テーブルマクロは `table_function()` で FROM に置きます。

```python
select(func.add(1, 2))  # SELECT add(?, ?)
select().from_(table_function(func.first_n(5), "t"))
drop_macro("add", if_exists=True)
drop_macro("first_n", table=True)  # DROP MACRO TABLE "first_n"
```

## シークレット {#secrets}

S3 などの認証情報を登録します。

```python
from parrotlet import create_secret, drop_secret

create_secret("s3", type="s3", key_id="...", secret="...", region="ap-northeast-1")
# CREATE SECRET "s3" (TYPE s3, KEY_ID '...', SECRET '...', REGION 'ap-northeast-1')

create_secret("prod", type="s3", persistent=True, provider="credential_chain")
# CREATE PERSISTENT SECRET "prod" (TYPE s3, PROVIDER 'credential_chain')

drop_secret("s3", if_exists=True)
```

| 引数 | 意味 |
|---|---|
| `name` | シークレットの名前（省略可） |
| `type` | `"s3"`、`"gcs"`、`"azure"`、`"http"` など |
| `persistent` | ディスクに保存する（既定は一時的） |
| `storage` | 保存先（`IN storage`） |
| `or_replace` / `if_not_exists` | 作成のオプション |
| その他のキーワード引数 | シークレットのオプション（`key_id`、`secret`、`region`、`scope` など） |

オプションの値はリテラルとして埋め込まれます。`type` は識別子として正しいかを検査し、そうでなければ `ValueError` になります。

`drop_secret()` の `persistent=True` / `False` で、`DROP PERSISTENT SECRET` / `DROP TEMPORARY SECRET` になります。

## DROP の一覧

| 関数 | SQL |
|---|---|
| `drop_table(name, *, if_exists, cascade)` | `DROP TABLE` |
| `drop_view(name, *, if_exists, cascade)` | `DROP VIEW` |
| `drop_sequence(name, *, if_exists, cascade)` | `DROP SEQUENCE` |
| `drop_index(name, *, if_exists)` | `DROP INDEX` |
| `drop_schema(name, *, if_exists, cascade)` | `DROP SCHEMA` |
| `drop_macro(name, *, if_exists, table=False)` | `DROP MACRO` / `DROP MACRO TABLE` |
| `drop_type(name, *, if_exists)` | `DROP TYPE` |
| `drop_secret(name, *, if_exists, persistent=None)` | <code>DROP [PERSISTENT &#124; TEMPORARY] SECRET</code> |
| `drop(kind, name, *, if_exists, cascade)` | 汎用（`kind` は `"TABLE"`、`"VIEW"` など） |

`comment_on(kind, name, comment)` も同じように、任意の種類のオブジェクトにコメントを付けます。
