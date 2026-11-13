# INSERT / UPDATE / DELETE / MERGE

データを変更するステートメントです。どれも `Database` から作れば `.execute()` でそのまま実行できます（`db.insert(...)`、`db.update(...)` など）。

変更した行を受け取りたいときは `.returning(...)` を付けます。`.returning()` がないステートメントに `.fetch_as()` を使うと `ValueError` になります。

## INSERT

```python
from parrotlet import DEFAULT, excluded, insert
```

### 値を入れる

`.values()` には、モデルのインスタンス、dict、タプルを渡せます。複数の行を一度に渡せます。

```python
insert(User).values(User(id=1, name="alice"), User(id=2, name="bob", age=30))
# INSERT INTO "users" ("id", "name", "age", "country", "tags", "joined")
#   VALUES (?, ?, ?, ?, ?, DEFAULT), (?, ?, ?, ?, ?, DEFAULT)

insert(User).values({"id": 1, "name": "alice"})
# INSERT INTO "users" ("id", "name") VALUES (?, ?)

insert(User, ["id", "name"]).values((1, "alice"), (2, DEFAULT))
# INSERT INTO "users" ("id", "name") VALUES (?, ?), (?, DEFAULT)

# カラムをあとから指定
insert(User).columns(User.id, User.name).values((1, "alice"))
```

| 行の形式 | カラム |
|---|---|
| モデルのインスタンス | モデルの全カラム。DB 側の既定値のカラムは `DEFAULT` になる |
| dict | 最初の dict のキー。以降の行も同じキーでなければ `ValueError` |
| タプル・リスト | `insert(T, [...])` または `.columns(...)` で指定した順。省略するとテーブルのカラム順 |

- 値には Python の値（パラメータになる）、式、`DEFAULT` を使えます。
- 行ごとに値の数が違うと `ValueError` になります。
- `.values()` を何度か呼ぶと、行が追加されます。

!!! tip "大量の行は appender で"
    数千行を超える投入には、INSERT より大幅に高速な [appender](database.md#appender) を使ってください。

### SELECT の結果を入れる

```python
insert(table("archive")).select(select(User).from_(User).where(User.age > 90))
# INSERT INTO "archive" SELECT "users".* FROM "users" WHERE ("users"."age" > ?)

insert(User).by_name().select(select(lit(1).as_("id"), lit("x").as_("name")))
# INSERT INTO "users" BY NAME SELECT 1 AS "id", 'x' AS "name"
```

`.by_name()` は、SELECT の結果のカラム名でテーブルのカラムと対応付けます（DuckDB の拡張）。`.by_position()` は位置で対応付けます（既定の動作を明示するだけです）。

### すべて既定値の行

```python
insert("counters").default_values()  # INSERT INTO "counters" DEFAULT VALUES
```

### 重複したときの処理

```python
insert(User).values(User(id=1, name="a")).or_replace()
# INSERT OR REPLACE INTO ...

insert(User, ["id", "name"]).values((1, "a")).or_ignore()
# INSERT OR IGNORE INTO ...

insert(User, ["id", "name"]).values((1, "a")).on_conflict_do_nothing(User.id)
# ... ON CONFLICT ("id") DO NOTHING

insert(User, ["id", "name", "age"]).values((1, "a", 3)).on_conflict_do_update(
    User.id,
    name=excluded.c.name,
    age=User.age + excluded.c.age,
)
# ... ON CONFLICT ("id") DO UPDATE SET
#   "name" = "excluded"."name", "age" = ("users"."age" + "excluded"."age")

insert(User, ["id", "name"]).values((1, "a")).on_conflict_do_update(
    "id",
    {User.name: excluded.c.name},
    where=User.name != excluded.c.name,
)
# ... DO UPDATE SET "name" = "excluded"."name"
#   WHERE ("users"."name" <> "excluded"."name")
```

| メソッド | 動作 |
|---|---|
| `.or_replace()` | 主キー・一意制約が重複したら、既存の行を置き換える |
| `.or_ignore()` | 重複した行は入れない |
| `.on_conflict_do_nothing(*target)` | `ON CONFLICT (target) DO NOTHING` |
| `.on_conflict_do_update(target, set=None, *, where=None, **kwargs)` | `ON CONFLICT (target) DO UPDATE SET ...` |

`excluded` は、入れようとした行を表すテーブルです。`excluded.c.<カラム>` で値を参照します。更新の値は dict（キーはカラム名か `User.name` などのカラム）でもキーワード引数でも指定できます。

### RETURNING と WITH

```python
q = db.insert(User).values(User(id=6, name="f")).returning(User.id, User.name)
q.fetchall()
# INSERT INTO ... RETURNING "users"."id", "users"."name"
# [(6, 'f')]

old = select(User).from_(User).cte("old")
insert(table("archive")).with_(old).select(select().from_("old"))
# WITH "old" AS (SELECT "users".* FROM "users")
#   INSERT INTO "archive" SELECT * FROM "old"
```

## UPDATE

```python
from parrotlet import update

(update(User).set({User.age: User.age + 1}, country="JP").where(User.id == 1).returning(User.age))
# UPDATE "users" SET "age" = ("users"."age" + ?), "country" = ?
#   WHERE ("users"."id" = ?) RETURNING "users"."age"
```

| メソッド | 意味 |
|---|---|
| `.set(values=None, /, **kwargs)` | 更新するカラムと値。dict のキーはカラム名か `User.age` などのカラム。複数回呼ぶと追加 |
| `.from_(*items)` | 他のテーブルを参照する `UPDATE ... FROM` |
| `.where(*conditions)` | 更新する行の条件（AND で結合） |
| `.returning(*items)` | 更新後の値を返す |
| `.with_(*ctes)` | CTE |

- 値には Python の値（パラメータ）も式も使えます。`set(age=None)` は NULL にします。
- `.set()` を呼ばずにビルドすると `ValueError` になります。
- `.where()` がなければ、すべての行が更新されます。

他のテーブルの値で更新するときは `.from_()` を使います。

```python
totals = select(Order.user_id, fn.sum(Order.amount).as_("total")).from_(Order).group_by(Order.user_id).subquery("t")
stats = table("stats")
(update(stats).set(total=totals.c.total).from_(totals).where(stats.c.user_id == totals.c.user_id))
# UPDATE "stats" SET "total" = "t"."total" FROM (SELECT ...) AS "t"
#   WHERE ("stats"."user_id" = "t"."user_id")
```

## DELETE / TRUNCATE

```python
from parrotlet import delete, truncate

delete(User).where(User.age.is_null()).returning(User.name)
# DELETE FROM "users" WHERE ("users"."age" IS NULL) RETURNING "users"."name"

delete(Order).using(User).where(Order.user_id == User.id, User.name == "bob")
# DELETE FROM "orders" USING "users"
#   WHERE (("orders"."user_id" = "users"."id") AND ("users"."name" = ?))

delete(User)  # DELETE FROM "users"（全行）
truncate(User)  # TRUNCATE "users"
```

| メソッド | 意味 |
|---|---|
| `.using(*items)` | 他のテーブルを参照する `DELETE ... USING` |
| `.where(*conditions)` | 削除する行の条件。省略すると全行を削除 |
| `.returning(*items)` | 削除した行の値を返す |
| `.with_(*ctes)` | CTE |

## MERGE

MERGE は、ソースの行とターゲットの行を突き合わせ、一致したかどうかで UPDATE・INSERT・DELETE を振り分けます。

```python
from parrotlet import merge_action, merge_into, values

staged = values((1, "alice2"), (9, "zed"), alias="s", columns=["id", "name"])
(
    merge_into(User)
    .using(staged, on=User.id == staged.c.id)
    .when_matched(staged.c.name != "skip")
    .update(name=staged.c.name)
    .when_not_matched()
    .insert({"id": staged.c.id, "name": staged.c.name})
    .when_not_matched_by_source()
    .delete()
    .returning(merge_action, User.id)
)
```

```sql
MERGE INTO "users"
USING (VALUES (?, ?), (?, ?)) AS "s"("id", "name") ON ("users"."id" = "s"."id")
WHEN MATCHED AND ("s"."name" <> ?) THEN UPDATE SET "name" = "s"."name"
WHEN NOT MATCHED THEN INSERT ("id", "name") VALUES ("s"."id", "s"."name")
WHEN NOT MATCHED BY SOURCE THEN DELETE
RETURNING "merge_action", "users"."id"
```

### ソースと突き合わせ

`.using(source, on=...)` か `.using(source, columns=...)` のどちらかで指定します。

```python
merge_into(User).using(table("staging"), on=User.id == table("staging").c.id)
merge_into(User).using(table("staging"), columns="id")  # USING ("id")
merge_into(User).using(table("staging"), columns=["id", "day"])
```

ソースには、テーブル、`values(...)`、サブクエリなど、FROM に置けるものを渡せます。

### WHEN 句とアクション

| 句 | 対象の行 |
|---|---|
| `.when_matched(cond=None)` | ソースとターゲットの両方にある行 |
| `.when_not_matched(cond=None)` | ソースにだけある行 |
| `.when_not_matched_by_source(cond=None)` | ターゲットにだけある行 |

`cond` を指定すると `WHEN MATCHED AND cond` になります。WHEN 句は上から順に評価され、最初に当てはまったものが使われます。

| アクション | SQL | 使える句 |
|---|---|---|
| `.update(values=None, **kwargs)` | `UPDATE SET col = value, ...` | matched / not matched by source |
| `.update_all()` | `UPDATE SET *`（位置で対応） | matched / not matched by source |
| `.update_by_name()` | `UPDATE BY NAME`（名前で対応） | matched / not matched by source |
| `.delete()` | `DELETE` | matched / not matched by source |
| `.insert(values, columns=())` | `INSERT (cols) VALUES (...)` | not matched |
| `.insert_all()` | `INSERT *` | not matched |
| `.insert_by_name()` | `INSERT BY NAME` | not matched |
| `.do_nothing()` | `DO NOTHING` | すべて |
| `.error(message=None)` | `ERROR 'message'`（MERGE を中止） | すべて |

`.insert()` には dict（カラム名 → 値）か、シーケンスと `columns=` を渡します。

```python
(
    merge_into(User)
    .using(table("staging"), columns="id")
    .when_matched(User.age > 100)
    .error("too old")
    .when_matched()
    .update_by_name()
    .when_not_matched()
    .insert_by_name()
)
```

`.returning()` に `merge_action` を含めると、各行にどのアクション（`INSERT` / `UPDATE` / `DELETE`）が適用されたかが返ります。

ソースを指定しなかったり、WHEN 句が1つもなかったりすると、ビルドするときに `ValueError` になります。

ファイルとテーブルの間でデータをコピーする COPY は[ファイルの読み書き](files.md)を参照してください。
