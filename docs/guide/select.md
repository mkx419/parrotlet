# SELECT

`select()` または `from_()` で SELECT 文を組み立てます。ビルダーは不変で、メソッドは常に新しいオブジェクトを返します。

```python
from parrotlet import from_, select

select(User.id, User.name).from_(User)
# SELECT "users"."id", "users"."name" FROM "users"

select().from_(User)  # SELECT * FROM "users"
select(User).from_(User)  # SELECT "users".* FROM "users"
from_(User)  # SELECT * FROM "users"（DuckDB の FROM 先頭構文）
from_(User).select(User.name)  # FROM を先に書いて、あとからカラムを足す
```

`Database` を使う場合は、`db.select(...)` / `db.from_(...)` で始めると、そのまま実行できます（[Database](database.md)）。

## メソッドの一覧

| メソッド | SQL | 複数回呼んだとき |
|---|---|---|
| `.select(*columns)` | SELECT リスト | 追加 |
| `.distinct(on=None)` | `DISTINCT` / `DISTINCT ON (...)` | 上書き |
| `.from_(*items)` | `FROM` | 追加（カンマ区切り） |
| `.join(...)` など | `JOIN` | 追加 |
| `.where(*conditions)` | `WHERE` | AND で結合 |
| `.group_by(*items)` / `.group_by_all()` | `GROUP BY` / `GROUP BY ALL` | 追加 |
| `.having(*conditions)` | `HAVING` | AND で結合 |
| `.window(name, spec)` | `WINDOW name AS (...)` | 追加 |
| `.qualify(*conditions)` | `QUALIFY` | AND で結合 |
| `.using_sample(...)` | `USING SAMPLE` | 上書き |
| `.order_by(*items)` / `.order_by_all(...)` | `ORDER BY` / `ORDER BY ALL` | 追加 |
| `.limit(n, offset=None, percent=False)` | `LIMIT n [OFFSET m]` / `LIMIT n%` | 上書き |
| `.offset(n)` | `OFFSET` | 上書き |
| `.with_(*ctes)` / `.with_recursive(*ctes)` | `WITH` / `WITH RECURSIVE` | 追加 |
| `.union()` / `.union_all()` / `.intersect()` / `.except_()` | 集合演算 | — |
| `.subquery(alias, ...)` | `(SELECT ...) AS alias` | — |
| `.cte(name, ...)` | CTE | — |
| `.scalar()` | スカラーサブクエリの式 | — |

句を書く順番は自由です。SQL は常に正しい順番で出力されます。

## SELECT リスト

SELECT リストには次のものを渡せます。

| 渡すもの | 例 | SQL |
|---|---|---|
| 式 | `User.name`、`fn.upper(User.name)` | `"users"."name"` など |
| 別名付きの式 | `fn.count().as_("n")` | `count(*) AS "n"` |
| カラム名の文字列 | `"name"` | `"name"` |
| `"*"` | `"*"` | `*` |
| モデル | `User` | `"users".*` |
| star 式 | `star(exclude=["tags"])` | `* EXCLUDE ("tags")`（[DuckDB 固有の機能](duckdb.md#star)） |
| `COLUMNS(...)` | `columns("num_.*")` | `COLUMNS('num_.*')` |
| サブクエリ | `select(...).scalar().as_("n")` | `(SELECT ...) AS "n"` |
| Python の値 | `1` | `?` |

カラムを指定しなければ `SELECT *` になります。

### DISTINCT

```python
select(User.country).from_(User).distinct()
# SELECT DISTINCT "users"."country" FROM "users"

(select(User.country, User.name).from_(User).distinct(on=User.country).order_by(User.country, User.age.desc()))
# SELECT DISTINCT ON ("users"."country") "users"."country", "users"."name"
#   FROM "users" ORDER BY "users"."country", "users"."age" DESC
```

`DISTINCT ON` は、`on` のカラムごとに、ORDER BY で最初に来る1行だけを残します（国ごとに最年長のユーザーなど）。`on` にはリストも渡せます。

## JOIN

```python
select(User.name, Order.amount).from_(User).join(Order, User.id == Order.user_id)
# SELECT ... FROM "users" INNER JOIN "orders" ON ("users"."id" = "orders"."user_id")
```

| メソッド | SQL | 説明 |
|---|---|---|
| `.join(t, on)` | `INNER JOIN` | 両方にある行 |
| `.left_join(t, on)` | `LEFT JOIN` | 左の行はすべて残す |
| `.right_join(t, on)` | `RIGHT JOIN` | 右の行はすべて残す |
| `.full_join(t, on)` | `FULL JOIN` | 両方の行をすべて残す |
| `.cross_join(t)` | `CROSS JOIN` | 直積 |
| `.natural_join(t)` | `NATURAL INNER JOIN` | 同じ名前のカラムで結合 |
| `.semi_join(t, on)` | `SEMI JOIN` | 右に一致する行がある左の行（`EXISTS` と同じ） |
| `.anti_join(t, on)` | `ANTI JOIN` | 右に一致する行がない左の行（`NOT EXISTS` と同じ） |
| `.asof_join(t, on, left=False)` | `ASOF JOIN` / `ASOF LEFT JOIN` | 不等号の条件で最も近い1行と結合 |
| `.positional_join(t)` | `POSITIONAL JOIN` | 行の位置で結合 |

条件は `on=`（BOOLEAN の式）か `using=`（カラム名）のどちらかで指定します。両方を指定すると `ValueError` になります。

```python
select().from_(table("a")).join(table("b"), using=["id", "day"])
# SELECT * FROM "a" INNER JOIN "b" USING ("id", "day")
```

### ASOF JOIN

時系列データで、「その時点で最新の値」と結合するときに使います。条件には不等号（`>=` など）を1つ含めます。

```python
prices = table("prices")
select(Order.id, prices.c.price).from_(Order).asof_join(prices, Order.ordered_at >= prices.c.ts)
# SELECT "orders"."id", "prices"."price" FROM "orders"
#   ASOF JOIN "prices" ON ("orders"."ordered_at" >= "prices"."ts")
```

一致する行がない左の行も残すときは `left=True` にします。等号の条件を加える（`(Order.item == prices.c.item) & (Order.ordered_at >= prices.c.ts)`）と、グループごとに最も近い行を探します。

JOIN に渡せるもの（サブクエリ、CTE、テーブル関数など）は FROM と同じです（[テーブルと FROM ソース](sources.md)）。

## WHERE

```python
(select(User.id).from_(User).where(User.age > 20, User.country == "JP").where(User.name.like("a%")))
# WHERE ((("users"."age" > ?) AND ("users"."country" = ?))
#   AND ("users"."name" LIKE ?))
```

複数の引数や、複数回の呼び出しは AND で結合されます。OR は `|` か `or_()` で書きます（[式](expressions.md#logic)）。WHERE には `Expr[Boolean]` しか渡せません。

## GROUP BY / HAVING

```python
(select(User.country, fn.count().as_("n")).from_(User).group_by(User.country).having(fn.count() > 1))
# SELECT "users"."country", count(*) AS "n" FROM "users"
#   GROUP BY "users"."country" HAVING (count(*) > ?)

select(User.country, fn.count()).from_(User).group_by_all()  # GROUP BY ALL
```

`group_by_all()` は、集約していないカラムすべてでグループ化します。ROLLUP / CUBE / GROUPING SETS は[集約とウィンドウ関数](aggregates.md#grouping)を参照してください。

## ORDER BY / LIMIT / OFFSET

```python
select().from_(User).order_by(User.age.desc(nulls="last"), User.name)
# ORDER BY "users"."age" DESC NULLS LAST, "users"."name"

select(User.name).from_(User).order_by_all(desc=True, nulls="last")
# ORDER BY ALL DESC NULLS LAST

select().from_(User).limit(10, offset=20)  # LIMIT ? OFFSET ?
select().from_(User).limit(10).offset(20)  # 同じ
select().from_(User).limit(10, percent=True)  # LIMIT ?%：全体の 10%
```

- `order_by()` には、式、`.asc()` / `.desc()` を付けた式、カラム名の文字列を渡せます。
- `order_by_all()` は、SELECT リストのすべてのカラムで並べ替えます。

## USING SAMPLE {#using-sample}

WHERE などを適用したあとの結果から、ランダムに行を取り出します。

```python
select().from_(User).using_sample(percent=10, method="bernoulli", seed=42)
# SELECT * FROM "users" USING SAMPLE 10 PERCENT (bernoulli, 42)

select().from_(User).using_sample(rows=100)  # USING SAMPLE 100 ROWS
```

テーブルを読む段階でサンプリングする `TABLESAMPLE` は[テーブルと FROM ソース](sources.md#sampling)を参照してください。

## サブクエリと CTE

```python
totals = select(Order.user_id, fn.sum(Order.amount).as_("total")).from_(Order).group_by(Order.user_id)

t = totals.subquery("t")  # FROM / JOIN に置くサブクエリ
select(User.name, t.c.total).from_(User).join(t, User.id == t.c.user_id)

c = totals.cte("totals")  # CTE
select(User.name, c.c.total).with_(c).from_(User).join(c, User.id == c.c.user_id)

avg = select(fn.avg(User.age)).from_(User).scalar()  # スカラーサブクエリ
select(User.name).from_(User).where(User.age > avg)

# 相関サブクエリ
n_orders = select(fn.count()).from_(Order).where(Order.user_id == User.id).scalar()
select(User.name, n_orders.as_("n")).from_(User)
# SELECT "users"."name",
#   (SELECT count(*) FROM "orders" WHERE ("orders"."user_id" = "users"."id")) AS "n"
# FROM "users"
```

詳しくは[テーブルと FROM ソース](sources.md#subqueries)を参照してください。

## 集合演算 {#set-operations}

```python
q1 = select(User.name).from_(User).where(User.country == "JP")
q2 = select(User.name).from_(User).where(User.age > 60)

q1.union(q2)  # UNION（重複を除く）
q1.union_all(q2)  # UNION ALL
q1.union(q2, by_name=True)  # UNION BY NAME（カラム名で対応付け）
q1.union(q2, all=True, by_name=True)  # UNION ALL BY NAME
q1.intersect(q2)  # INTERSECT / intersect(q2, all=True) で INTERSECT ALL
q1.except_(q2)  # EXCEPT / except_(q2, all=True) で EXCEPT ALL
```

```sql
(SELECT "users"."name" FROM "users" WHERE ("users"."country" = ?))
UNION
(SELECT "users"."name" FROM "users" WHERE ("users"."age" > ?))
```

結果（`Compound`）にも `.order_by()`、`.limit()`、`.with_()`、`.subquery()`、`.cte()` が使えます。これらは集合演算の結果全体にかかります。

```python
q1.union(q2).union(q3).order_by("name").limit(5)
# (SELECT ...) UNION (SELECT ...) UNION (SELECT ...) ORDER BY "name" LIMIT ?
```

各クエリは括弧で囲まれるので、それぞれのクエリに ORDER BY や LIMIT を付けても、意味が変わりません。

ORDER BY / LIMIT / OFFSET / WITH を付けた集合演算に、さらに `.union()` などをつなげると、前の集合演算全体が括弧で囲まれます。LIMIT は内側の集合演算にだけかかります。

```python
q1.union(q2).order_by("name").limit(5).union(q3)
# ((SELECT ...) UNION (SELECT ...) ORDER BY "name" LIMIT ?) UNION (SELECT ...)
```

## PIVOT / UNPIVOT

PIVOT は、カラムの値ごとに新しいカラムを作ります。

```python
from parrotlet import pivot, unpivot

(
    pivot(Order)
    .on(Order.status, values=["pending", "paid"])
    .using(fn.sum(Order.amount).as_("total"))
    .group_by(Order.user_id)
)
# PIVOT "orders" ON "status" IN (?, ?)
#   USING sum("amount") AS "total" GROUP BY "user_id"
```

| メソッド | 意味 |
|---|---|
| `.on(column, values=None)` | このカラムの値ごとにカラムを作る。複数回呼ぶと組み合わせごとのカラムになる |
| `.using(*aggregates)` | セルの値を計算する集約関数 |
| `.group_by(*columns)` | 行としてまとめるカラム |
| `.order_by()` / `.limit()` / `.with_()` | SELECT と同じ |

- `values=` を省略すると、DuckDB が値を自動で列挙します。その場合、出力されるカラムはデータによって変わります。
- PIVOT の中では、カラムはテーブル名なしで出力されます。
- 単独の文として実行できるほか、`.subquery("p")` で FROM に置けます。

UNPIVOT は、複数のカラムを行に変換します。

```python
unpivot("monthly").on(columns("m_.*")).into(name="month", value="amount")
# UNPIVOT "monthly" ON COLUMNS('m_.*') INTO NAME "month" VALUE "amount"

unpivot("wide").on("jan", "feb").into(name="month", value="amount")
# UNPIVOT "wide" ON "jan", "feb" INTO NAME "month" VALUE "amount"
```

`into()` を省略すると、カラム名は `name` と `value` になります。

!!! note "IN リストのない PIVOT とパラメータ"
    `values=` のない PIVOT をサブクエリにすると、DuckDB は内部で複数の文に展開するので、パラメータを使えません。parrotlet はこのエラーを検出し、値をリテラルとして埋め込んで1回だけ自動で再実行します。

## SQL の確認

```python
q.sql  # パラメータ（?）付きの SQL
q.params  # パラメータの値のタプル
q.sql_inline  # 値をリテラルとして埋め込んだ SQL（ログ・デバッグ用）
str(q)  # q.sql と同じ
q.build()  # Query(sql, params, extensions)
```

`sql_inline` は、ログに出したり DuckDB の CLI に貼り付けたりするのに便利です。実行には `?` 付きの SQL が使われます。
