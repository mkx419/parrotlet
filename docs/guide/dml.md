# INSERT / UPDATE / DELETE / MERGE

## INSERT

```python
from parrotlet import DEFAULT, excluded, insert

insert(User).values(User(id=1, name="alice"))  # モデルのインスタンス
insert(User).values({"id": 1, "name": "alice"})  # dict（キーがカラム名）
insert(User, ["id", "name"]).values((1, "alice"), (2, DEFAULT))
insert(User).select(select(...).from_(...))
insert(User).by_name().select(...)  # BY NAME / by_position()
insert(User).default_values()
insert(User).values(...).or_replace()  # INSERT OR REPLACE / or_ignore()
insert(User, ["id", "name"]).values((1, "x")).on_conflict_do_nothing("id")
insert(User, ["id", "name"]).values((1, "x")).on_conflict_do_update("id", name=excluded.c.name)
insert(User).values(...).returning(User.id)
```

大量の行を投入するときは、INSERT より高速な [appender](database.md#appender) を使ってください。

## UPDATE

```python
from parrotlet import update

update(User).set({User.age: User.age + 1}, country="JP").where(User.id == 1).returning(User.age)
update(User).set(total=t.c.total).from_(t).where(User.id == t.c.user_id)
```

## DELETE / TRUNCATE

```python
from parrotlet import delete, truncate

delete(User).where(User.age.is_null()).returning(User.name)
delete(Order).using(User).where(Order.customer_id == User.id, User.name == "bob")
truncate(User)
```

## MERGE

```python
from parrotlet import merge_action, merge_into, values

staged = values((1, "alice2"), (9, "zed"), alias="s", columns=["id", "name"])
(
    merge_into(User)
    .using(staged, on=User.id == staged.c.id)  # または columns="id"（USING (id)）
    .when_matched(staged.c.name != "skip")
    .update(name=staged.c.name)
    .when_not_matched()
    .insert({"id": staged.c.id, "name": staged.c.name})
    .when_not_matched_by_source()
    .delete()
    .returning(merge_action, User.id)
)
```

| 句 | 使えるアクション |
|---|---|
| `when_matched()` / `when_not_matched_by_source()` | `update(...)`、`update_all()`（`UPDATE SET *`）、`update_by_name()`、`delete()`、`do_nothing()`、`error("message")` |
| `when_not_matched()` | `insert(values)`、`insert_all()`（`INSERT *`）、`insert_by_name()`、`do_nothing()`、`error()` |

## COPY

```python
from parrotlet import copy_database, copy_from, copy_to

copy_to(select(...).from_(...), "out.parquet", format="parquet", compression="zstd")
copy_to(User, "users", format="parquet", partition_by=["country"], overwrite_or_ignore=True)
copy_from(User, "users.csv", header=True, delimiter="|")
copy_database("memory", "backup")
```

オプションには、DuckDB の COPY オプションを名前で指定します（大文字小文字は問いません）。
