# DDL

DuckDB の DDL はパラメータを受け付けないため、DDL に含まれる値は、エスケープ済みのリテラルとしてインライン展開されます。

## テーブル

テーブルの作成は[モデル](models.md)を参照してください（`create_table(Model)`、`db.register`）。

```python
from parrotlet import alter_table, comment_on_column, comment_on_table, drop_table

alter_table(User).add_column("score", dt.INTEGER, default=0, if_not_exists=True)
alter_table(User).drop_column("score", if_exists=True)
alter_table(User).rename_column("score", "points")
alter_table(User).rename_to("members")
alter_table(User).alter_type("points", dt.BIGINT, using=col("points") * 10)
alter_table(User).set_default("points", 0)
alter_table(User).drop_default("points")
alter_table(User).set_not_null("name")
alter_table(User).drop_not_null("name")
alter_table("t").add_primary_key("id")

comment_on_table(User, "registered users")
comment_on_column(User.name, "display name")
drop_table(User, if_exists=True, cascade=True)
```

DuckDB では1つの ALTER TABLE で1つの操作しかできないため、`alter_table(T).<操作>()` はそれぞれ1文になります。

## ビュー・スキーマ・シーケンス・インデックス・型

```python
from parrotlet import create_index, create_schema, create_sequence, create_type, create_view

create_view("adults", select(User).from_(User).where(User.age >= 20), or_replace=True)
create_schema("analytics", if_not_exists=True)
create_sequence("user_ids", start=1, increment=1)  # F.nextval("user_ids") と組み合わせる
create_index("ix_users_name", User, User.name, F.lower(User.name), unique=False)
create_type("mood", dt.ENUM("sad", "ok", "happy"))
```

## マクロ

Python のラムダから CREATE MACRO を作ります。ラムダの引数がマクロの引数に、Python の既定値が `name := value` になります。

```python
from parrotlet import create_macro, func

create_macro("add", lambda a, b=1: a + b)  # CREATE MACRO add(a, b := 1) AS (a + b)
create_macro("first_n", lambda n: select().from_(TF.range(n)))  # 本体が文ならテーブルマクロ
create_macro("f", lambda a: a, lambda a, b: a * b)  # 引数の数によるオーバーロード

select(func.add(1, 2))  # 作ったマクロは func.<name> で呼べる
```

## シークレット

```python
from parrotlet import create_secret, drop_secret

create_secret("s3", type="s3", key_id="...", secret="...", region="ap-northeast-1")
create_secret("prod", type="s3", persistent=True, provider="credential_chain")
drop_secret("s3", if_exists=True)
```

## DROP

`drop_table` / `drop_view` / `drop_sequence` / `drop_index` / `drop_schema` / `drop_macro(table=...)` / `drop_type` / `drop_secret`、または汎用の `drop(kind, name, if_exists=, cascade=)` を使います。
