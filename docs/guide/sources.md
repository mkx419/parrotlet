# テーブルと FROM ソース

モデルを定義していないテーブル、サブクエリ、CTE、ファイル、テーブル関数など、FROM や JOIN に置けるものの書き方を説明します。

## FROM に渡せるもの

| 渡すもの | 例 | SQL |
|---|---|---|
| モデル | `User` | `"users"` |
| テーブル名の文字列 | `"users"` | `"users"` |
| テーブル参照 | `table("events", schema="raw")` | `"raw"."events"` |
| 別名付きのテーブル | `table("t").as_("x", ["c1", "c2"])` | `"t" AS "x"("c1", "c2")` |
| サブクエリ | `select(...).subquery("s")` | `(SELECT ...) AS "s"` |
| CTE | `q.cte("c")`（`.with_()` と組み合わせる） | `"c"` |
| テーブル関数 | `fn.table.read_parquet("x.parquet").as_("p")` | `read_parquet(?) AS "p"` |
| VALUES | `values((1, "a"), alias="v", columns=["k", "s"])` | `(VALUES (?, ?)) AS "v"("k", "s")` |
| ファイル | `file("data/*.parquet")` | `'data/*.parquet'` |
| サンプリング | `tablesample(User, percent=10)` | `"users" TABLESAMPLE 10 PERCENT` |
| PIVOT / UNPIVOT | `pivot(...).subquery("p")` | `(PIVOT ...) AS "p"` |

ステートメントをそのまま FROM に渡すとエラーになります。`.subquery("名前")` で別名を付けてください。

## モデルのないテーブル

`table()` で、名前だけでテーブルを参照できます。

```python
from parrotlet import table

events = table("events")
select(events.c.kind, fn.count()).from_(events).group_by(events.c.kind)
# SELECT "events"."kind", count(*) FROM "events" GROUP BY "events"."kind"

table("events", schema="raw", catalog="lake")  # "lake"."raw"."events"
```

カラムは次のどれでも参照できます。どれも型なし（`ColumnRef[Any]`）です。

```python
events.c.kind  # 属性で
events.c["first name"]  # 識別子にできない名前
events["kind"]  # events.c["kind"] と同じ
events.col("kind")
```

`col()` でも直接カラムを作れます。テーブル名を省略すると、修飾なしのカラム名になります。

```python
from parrotlet import col

col("kind")  # "kind"
col("kind", "events")  # "events"."kind"
col("ts", "events", type_=qlt.Timestamp)  # 型付き：ColumnRef[Timestamp]
```

カラム参照の場所では、文字列もカラム名として扱われます（`select("name")`、`order_by("name")`、`group_by("country")` など）。

## 別名

```python
u = table("users").as_("u")
select(u.c.name).from_(u)  # SELECT "u"."name" FROM "users" AS "u"

t = table("t").as_("x", ["c1", "c2"])  # カラム名も付け替える
select(t.c.c1).from_(t)  # SELECT "x"."c1" FROM "t" AS "x"("c1", "c2")
```

モデルに型付きの別名を付けるときは [`aliased()`](models.md#aliased) を使います。

## サブクエリ {#subqueries}

```python
totals = select(Order.user_id, fn.sum(Order.amount).as_("total")).from_(Order).group_by(Order.user_id)
t = totals.subquery("t")

select(User.name, t.c.total).from_(User).join(t, User.id == t.c.user_id)
```

```sql
SELECT "users"."name", "t"."total"
FROM "users" INNER JOIN (
  SELECT "orders"."user_id", sum("orders"."amount") AS "total"
  FROM "orders" GROUP BY "orders"."user_id"
) AS "t" ON ("users"."id" = "t"."user_id")
```

| `subquery()` の引数 | 意味 |
|---|---|
| `alias` | 別名（必須） |
| `columns` | 出力カラムの名前を付け替える：`AS "t"("uid", "tot")` |
| `lateral` | `LATERAL` サブクエリにする（外側の行を参照できる） |

```python
top = (
    select(Order.amount)
    .from_(Order)
    .where(Order.user_id == User.id)  # 外側の User を参照
    .order_by(Order.amount.desc())
    .limit(1)
    .subquery("top", lateral=True)
)
select(User.name, top.c.amount).from_(User).cross_join(top)
# ... FROM "users" CROSS JOIN LATERAL (
#   SELECT ... WHERE ("orders"."user_id" = "users"."id") ...
# ) AS "top"
```

WHERE や SELECT の中で使うスカラーサブクエリ、`IN (subquery)`、`EXISTS` は[式](expressions.md#subqueries)を参照してください。

## CTE（WITH） {#cte}

`.cte(name)` で CTE を作り、`.with_()` で登録してから、テーブルとして参照します。

```python
paid = select(Order).from_(Order).where(Order.status == "paid").cte("paid")
select(fn.count()).with_(paid).from_(paid)
# WITH "paid" AS (SELECT "orders".* FROM "orders" WHERE ("orders"."status" = ?))
#   SELECT count(*) FROM "paid"
```

CTE のカラムは `paid.c.amount` で参照します。

| `cte()` の引数 | 意味 |
|---|---|
| `name` | CTE の名前 |
| `columns` | カラム名のリスト：`"c" ("a", "b") AS (...)` |
| `materialized` | `True` で `AS MATERIALIZED`、`False` で `AS NOT MATERIALIZED` |
| `using_key` | 再帰 CTE で DuckDB の `USING KEY (...)` を使う |

`.with_()` は INSERT / UPDATE / DELETE / MERGE にもあります。

### 再帰 CTE

```python
r = table("r")
base = select(lit(1).as_("n"))
step = select(r.c.n + 1).from_(r).where(r.c.n < 10)

select().with_recursive(base.union_all(step).cte("r", columns=["n"])).from_(r)
```

```sql
WITH RECURSIVE "r" ("n") AS (
  (SELECT 1 AS "n") UNION ALL (SELECT ("r"."n" + ?) FROM "r" WHERE ("r"."n" < ?))
) SELECT * FROM "r"
```

再帰の中で自分自身を参照するには、`table("r")` で同じ名前のテーブルを使います。

## テーブル関数 {#table-functions}

`parrotlet.functions.table`（`fn.table`）の関数は、FROM で使うソースを返します。

```python
select().from_(fn.table.read_parquet("data/*.parquet", hive_partitioning=True).as_("p"))
# SELECT * FROM read_parquet(?, "hive_partitioning" := ?) AS "p"

r = fn.table.range(10).as_("r")
select(r.c.range).from_(r)  # SELECT "r"."range" FROM range(?) AS "r"

select().from_(fn.table.unnest([1, 2, 3]).as_("u", ["x"]).with_ordinality())
# SELECT * FROM unnest(?) WITH ORDINALITY AS "u"("x")
```

- 先頭の引数は位置引数、残りのオプションはキーワード引数（SQL では `name := value`）です。
- カラムを参照するには、`.as_("別名")` で別名を付けます。別名のないテーブル関数の `.c` を使うと `ValueError` になります。
- `.with_ordinality()` は、1 始まりの行番号のカラムを追加します。

自作のテーブルマクロなど、`fn.table` にない関数は `table_function()` で FROM に置けます。

```python
from parrotlet import func, table_function

select().from_(table_function(func.my_table_macro(1), "t"))
# SELECT * FROM my_table_macro(?) AS "t"
```

ファイルの読み込みについては[ファイルの読み書き](files.md)も参照してください。

## VALUES

```python
from parrotlet import values

v = values((1, "a"), (2, "b"), alias="v", columns=["k", "s"])
select(v.c.k, v.c.s).from_(v)
# SELECT "v"."k", "v"."s" FROM (VALUES (?, ?), (?, ?)) AS "v"("k", "s")
```

`alias` の既定値は `"values"` です。行ごとに値の数が違うと `ValueError` になります。MERGE のソースとしてもよく使います（[MERGE](dml.md#merge)）。

## ファイル

DuckDB は、ファイルのパスを FROM に書くだけで読み込めます（形式は拡張子から判定されます）。

```python
from parrotlet import file

select().from_(file("data/*.parquet"))  # SELECT * FROM 'data/*.parquet'

f = file("logs/*.csv").as_("f")
select(f.c.level, fn.count()).from_(f).group_by(f.c.level)
# SELECT "f"."level", count(*) FROM 'logs/*.csv' AS "f" GROUP BY "f"."level"
```

パスはパラメータではなく、リテラルとして埋め込まれます。DuckDB がテーブルの位置にパラメータを受け付けないためです。

## サンプリング {#sampling}

```python
from parrotlet import tablesample

select().from_(tablesample(User, percent=10))  # FROM "users" TABLESAMPLE 10 PERCENT
select().from_(table("t").tablesample(rows=100, method="reservoir", seed=1))
# FROM "t" TABLESAMPLE reservoir(100 ROWS) REPEATABLE (1)
```

| 引数 | 意味 |
|---|---|
| `percent` / `rows` | どちらか1つを指定する |
| `method` | `"reservoir"` / `"bernoulli"` / `"system"` |
| `seed` | 乱数の種（再現性のため） |

フィルター後の結果をサンプリングする `USING SAMPLE` は [SELECT](select.md#using-sample) を参照してください。
