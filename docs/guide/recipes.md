# レシピ集

よくある処理の書き方です。例は[はじめに](getting-started.md#sample-models)の `User` と `Order` を使います。

## 条件を動的に組み立てる

ビルダーは不変なので、条件に応じて `.where()` をつなげた新しいクエリを作れます。

```python
from parrotlet import Select


def search(
    name: str | None = None,
    country: str | None = None,
    min_age: int | None = None,
) -> Select:
    q = db.from_(User)
    if name is not None:
        q = q.where(User.name.ilike(f"%{name}%"))  # 値はパラメータになるので安全
    if country is not None:
        q = q.where(User.country == country)
    if min_age is not None:
        q = q.where(User.age >= min_age)
    return q.order_by(User.id)


search(country="JP", min_age=26).fetch_as(User)
```

条件をリストに集めて、`.where(*conditions)` にまとめて渡すこともできます。条件が空なら WHERE は付きません。

## ページング

```python
def page(n: int, size: int = 20) -> Select:
    return db.from_(User).order_by(User.id).limit(size, offset=(n - 1) * size)
```

大きなテーブルでは、OFFSET より、最後に見たキーから続きを取るほうが速くなります（キーセットページング）。

```python
db.from_(User).where(User.id > last_id).order_by(User.id).limit(20).fetch_as(User)
```

## グループごとの上位 N 件

`QUALIFY` を使うと、サブクエリなしで書けます。

```python
rn = fn.row_number().over(partition_by=User.country, order_by=User.age.desc(nulls="last"))
oldest_per_country = db.select(User.country, User.name, User.age).from_(User).qualify(rn <= 1)
```

1件だけでよければ `DISTINCT ON` も使えます。

```python
latest_order = (
    db.select(Order.user_id, Order.id)
    .from_(Order)
    .distinct(on=Order.user_id)
    .order_by(Order.user_id, Order.ordered_at.desc())
)
```

## upsert（あれば更新、なければ追加）

```python
db.insert(User).values(
    User(id=2, name="bobby", age=26),
    User(id=5, name="eve", age=22),
).on_conflict_do_update(User.id, name=excluded.c.name, age=excluded.c.age).execute()
```

| 方法 | 向いている場面 |
|---|---|
| `insert(...).on_conflict_do_update(...)` | 更新するカラムや条件を細かく決めたい |
| `insert(...).or_replace()` | 行全体を置き換えればよい |
| `db.appender(T, action="upsert")` | 大量の行 |
| `merge_into(...)` | 削除も含めて同期したい（後述） |

## テーブルを同期する（MERGE）

```python
staged = values((4, "DAVE"), (9, "zed"), alias="s", columns=["id", "name"])
(
    db.merge_into(User)
    .using(staged, on=User.id == staged.c.id)
    .when_matched()
    .update(name=staged.c.name)
    .when_not_matched()
    .insert({"id": staged.c.id, "name": staged.c.name, "tags": []})
    .returning(merge_action, User.id)
    .fetchall()
)
# [('UPDATE', 4), ('INSERT', 9)]
```

ソースのテーブルにない行を消すときは `.when_not_matched_by_source().delete()` を加えます。

## 集計：0 件のグループも含める

LEFT JOIN と `coalesce` を組み合わせます。条件は WHERE ではなく JOIN の ON に書きます（WHERE に書くと、注文のないユーザーが消えます）。

```python
(
    db.select(
        User.name,
        fn.coalesce(fn.sum(Order.amount), 0).as_("total"),
        fn.count(Order.id).as_("n"),
    )
    .from_(User)
    .left_join(Order, (User.id == Order.user_id) & (Order.status == "paid"))
    .group_by(User.name)
)
```

## 累計と構成比

```python
running = fn.sum(Order.amount).over(order_by=Order.ordered_at, frame=rows_between(None, 0))
db.select(
    Order.id,
    running.as_("running"),
    (Order.amount / fn.sum(Order.amount).over() * 100).as_("pct"),
).from_(Order).order_by(Order.ordered_at)
```

## 日ごとの集計（データのない日も 0 で埋める）

`generate_series` で日付の一覧を作り、集計結果を LEFT JOIN します。

```python
from datetime import datetime, timedelta

days = fn.table.generate_series(datetime(2026, 1, 1), datetime(2026, 1, 31), timedelta(days=1)).as_("d", ["day"])
daily = (
    db.select(
        fn.date_trunc("day", Order.ordered_at).as_("day"),
        fn.sum(Order.amount).as_("total"),
    )
    .from_(Order)
    .group_by_all()
    .subquery("s")
)
(
    db.select(days.c.day, fn.coalesce(daily.c.total, 0).as_("total"))
    .from_(days)
    .left_join(daily, using="day")
    .order_by(days.c.day)
)
```

## 行が存在するか・しないか

```python
# 注文のないユーザー
db.select(User.name).from_(User).anti_join(Order, User.id == Order.user_id)

# 注文のあるユーザー
db.select(User.name).from_(User).semi_join(Order, User.id == Order.user_id)

paid = select(1).from_(Order).where(Order.user_id == User.id, Order.status == "paid")
db.select(User.name).from_(User).where(exists(paid))
```

## クエリの部品を使い回す

式もステートメントも普通の Python の値なので、変数や関数にできます。

```python
is_adult = User.age >= 20  # 条件

# SELECT の項目
display_name = fn.coalesce(User.name, "(no name)").as_("display_name")


def paid_orders() -> Select:  # クエリの一部
    return select(Order).from_(Order).where(Order.status == "paid")


db.bind(paid_orders().where(Order.amount >= 50)).fetchall()
db.select(display_name).from_(User).where(is_adult).fetchall()
```

## クロス集計（PIVOT）

```python
db.execute(
    pivot(Order)
    .on(Order.status, values=["paid", "pending"])
    .using(fn.sum(Order.amount))
    .group_by(Order.user_id)
    .order_by(Order.user_id)
).fetchall()
# [(1, Decimal('150.000'), None),
#  (2, None, Decimal('70.000')),
#  (3, Decimal('30.000'), None)]
```

## Parquet で ETL

```python
# 書き出す
db.execute(copy_to(select(Order).from_(Order), "orders.parquet", format="parquet"))

# 読む
src = file("orders.parquet").as_("src")
db.select(fn.count(), fn.sum(src.c.amount)).from_(src).fetchone()

# パーティションで書く
db.execute(copy_to(Order, "by_status", format="parquet", partition_by=["status"]))
p = fn.table.read_parquet("by_status/**/*.parquet", hive_partitioning=True).as_("p")
db.select(p.c.status, fn.count()).from_(p).group_by_all().fetchall()
```

## JSON のカラム

```python
payload = col("payload", "events", type_=qlt.Json)
db.select(
    payload.json_get_text("$.user.name"),
    payload.json_get("$.n").cast(qlt.Integer),
).from_(table("events"))
```

## リストのカラム

```python
db.select(User.name).from_(User).where(fn.list_contains(User.tags, "admin"))
db.select(User.name, fn.len(User.tags)).from_(User)

# 1要素1行に展開
db.select(User.name, func.unnest(User.tags).as_("tag")).from_(User)
```

## 大量の更新

数万行を個別に UPDATE するより、appender の `update` のほうが速くなります。

```python
with db.appender(User, action="update", columns=[User.id, User.age]) as app:
    # name は使われない
    app.extend(User(id=i, name="", age=age) for i, age in new_ages.items())
```

## SQL をログに出す

```python
import logging

log = logging.getLogger("sql")
q = db.from_(User).where(User.id == 1)
log.debug("%s %s", q.sql, q.params)  # パラメータ付き
log.debug(q.sql_inline)  # 値を埋め込んだ SQL（そのまま DuckDB の CLI に貼れる）
```

## テストでインメモリのデータベースを使う

```python
import pytest


@pytest.fixture
def db() -> Database:
    db = Database()  # テストごとに新しいインメモリ DB
    db.register(User)
    db.register(Order)
    return db


def test_count(db: Database) -> None:
    db.insert(User).values(User(id=1, name="x")).execute()
    assert db.select(fn.count()).from_(User).fetchone() == (1,)
```

SQL の文字列そのものをテストしたいときは、`q.sql` と `q.params` を比べます。
