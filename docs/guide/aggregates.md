# 集約とウィンドウ関数

## 集約関数

集約関数は、`GROUP BY` でまとめた行（GROUP BY がなければ全体）から1つの値を計算します。

```python
select(
    User.country,
    fn.count().as_("n"),
    fn.avg(User.age).as_("avg_age"),
    fn.max(User.joined).as_("latest"),
).from_(User).group_by(User.country)
```

よく使う集約関数は次のとおりです。

| 関数 | 意味 | 結果の型 |
|---|---|---|
| `fn.count()` | 行数（`count(*)`） | `BigInt` |
| `fn.count(x)` | NULL でない値の数 | `BigInt` |
| `fn.sum(x)` | 合計 | 整数は `HugeInt`、DECIMAL は `Decimal`、浮動小数点数は `Double` |
| `fn.avg(x)` / `fn.median(x)` | 平均 / 中央値 | `Double` など |
| `fn.min(x)` / `fn.max(x)` | 最小 / 最大 | `x` と同じ型 |
| `fn.arg_min(v, x)` / `fn.arg_max(v, x)` | `x` が最小 / 最大の行の `v` | `v` と同じ型 |
| `fn.first(x)` / `fn.last(x)` / `fn.any_value(x)` | 最初 / 最後 / 任意の値 | `x` と同じ型 |
| `fn.mode(x)` | 最頻値 | `x` と同じ型 |
| `fn.list(x)` / `fn.array_agg(x)` | リストにまとめる | `List[...]` |
| `fn.string_agg(x, sep)` | 文字列を連結する | `Varchar` |
| `fn.bool_and(x)` / `fn.bool_or(x)` | すべて / どれかが真 | `Boolean` |
| `fn.quantile_cont(x, q)` / `fn.quantile_disc(x, q)` | 分位数 | — |
| `fn.approx_count_distinct(x)` | 近似の異なり数 | `BigInt` |
| `fn.histogram(x)` | 値ごとの件数 | `Map` |

ほかの集約関数も、すべて `fn.<名前>` で使えます（[関数](functions.md)）。

### DISTINCT・ORDER BY・FILTER

集約関数には、次の引数とメソッドがあります。

```python
fn.count(User.country, distinct=True)
# count(DISTINCT "users"."country")

fn.string_agg(User.name, ",", order_by=User.name.desc())
# string_agg("users"."name", ? ORDER BY "users"."name" DESC)

fn.list(User.name, order_by=User.age)
# list("users"."name" ORDER BY "users"."age")

fn.count().filter(Order.status == "paid")
# count(*) FILTER (WHERE ("orders"."status" = ?))

fn.sum(Order.amount).filter(Order.status == "paid").filter(Order.amount > 0)
# sum("orders"."amount")
#   FILTER (WHERE (("orders"."status" = ?) AND ("orders"."amount" > ?)))
```

| 書き方 | 意味 |
|---|---|
| `distinct=True` | 重複を除いて集約する |
| `order_by=...` | 集約する順番（順序付き集約）。リストも渡せる |
| `.filter(cond)` | 条件に合う行だけを集約する。複数回呼ぶと AND で結合 |

`FILTER` を使うと、1つのクエリで条件ごとの集計を並べられます。

```python
select(
    Order.user_id,
    fn.count().filter(Order.status == "paid").as_("paid"),
    fn.count().filter(Order.status == "cancelled").as_("cancelled"),
).from_(Order).group_by(Order.user_id)
```

## グループ化の拡張 {#grouping}

```python
from parrotlet import cube, grouping_sets, rollup

q = select(User.country, User.age, fn.count()).from_(User)

q.group_by(rollup(User.country, User.age))
# GROUP BY ROLLUP ("users"."country", "users"."age")

q.group_by(cube(User.country, User.age))
# GROUP BY CUBE ("users"."country", "users"."age")

q.group_by(grouping_sets([User.country], [User.age], []))
# GROUP BY GROUPING SETS (("users"."country"), ("users"."age"), ())
```

| 書き方 | 集計の単位 |
|---|---|
| `rollup(a, b)` | `(a, b)`、`(a)`、全体 |
| `cube(a, b)` | `(a, b)`、`(a)`、`(b)`、全体 |
| `grouping_sets([a], [b], [])` | 指定した組み合わせ（`[]` は全体） |

どの行がどの単位の集計かは、`func.grouping(User.country)` で判定できます（`GROUPING` は DuckDB の構文なので、型付きの関数はありません）。

## ウィンドウ関数

ウィンドウ関数は、行をまとめずに、各行について「関連する行の集まり」（ウィンドウ）から値を計算します。`.over(...)` でウィンドウを指定します。

```python
rn = fn.row_number().over(partition_by=User.country, order_by=User.age.desc())
select(User.name, rn.as_("rn")).from_(User)
# SELECT "users"."name",
#   row_number() OVER (
#     PARTITION BY "users"."country" ORDER BY "users"."age" DESC
#   ) AS "rn"
# FROM "users"
```

| `.over()` の引数 | SQL |
|---|---|
| `partition_by` | `PARTITION BY`（式、またはそのリスト） |
| `order_by` | `ORDER BY`（式、`.desc()` 付きの式、またはそのリスト） |
| `frame` | フレーム（後述） |
| 第1引数 | 名前付きウィンドウの名前、または `window(...)` |

### ウィンドウ専用の関数

| 関数 | 意味 |
|---|---|
| `fn.row_number()` | 1 からの連番 |
| `fn.rank()` / `fn.dense_rank()` | 順位（同順位の扱いが違う） |
| `fn.percent_rank()` / `fn.cume_dist()` | 相対順位 / 累積分布 |
| `fn.ntile(n)` | n 個のグループに分けた番号 |
| `fn.lag(x, offset=1, default=None)` / `fn.lead(...)` | 前 / 後の行の値 |
| `fn.first_value(x)` / `fn.last_value(x)` / `fn.nth_value(x, n)` | ウィンドウ内の最初 / 最後 / n 番目の値 |

これらは `WindowFunc` を返し、`.over(...)` を付けるまで式として使えません。`select(fn.row_number())` は型エラーになります。

```python
fn.lag(Order.amount, 1, 0).over(partition_by=Order.user_id, order_by=Order.ordered_at)
# lag("orders"."amount", ?, ?)
#   OVER (PARTITION BY "orders"."user_id" ORDER BY "orders"."ordered_at")

fn.first_value(Order.amount, ignore_nulls=True).over(partition_by=Order.user_id, order_by=Order.ordered_at)
# first_value("orders"."amount" IGNORE NULLS) OVER (...)
```

ウィンドウ関数には `ignore_nulls=`（NULL を無視する）と `order_by=`（関数の中の ORDER BY）を指定できます。

### 集約関数をウィンドウで使う

集約関数にも `.over()` を付けられます。グループ化せずに、各行に集計値を付けられます。

```python
user_total = fn.sum(Order.amount).over(partition_by=Order.user_id)
select(Order.id, Order.amount, user_total.as_("user_total")).from_(Order)
# sum("orders"."amount") OVER (PARTITION BY "orders"."user_id") AS "user_total"
```

### フレーム

フレームは、ウィンドウのうち、どの範囲の行を計算に使うかを指定します。

```python
from datetime import timedelta
from parrotlet import groups_between, range_between, rows_between

# 累計：先頭から現在の行まで
fn.sum(Order.amount).over(order_by=Order.ordered_at, frame=rows_between(None, 0))
# ... ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW

# 移動平均：前後2行（現在の行を除く）
fn.avg(Order.amount).over(order_by=Order.id, frame=rows_between(-2, 2, exclude="current row"))
# ... ROWS BETWEEN 2 PRECEDING AND 2 FOLLOWING EXCLUDE CURRENT ROW

# 直近7日間：ORDER BY の値の範囲で指定
fn.sum(Order.amount).over(order_by=Order.ordered_at, frame=range_between(-timedelta(days=7), 0))
# ... RANGE BETWEEN INTERVAL '604800000000 microseconds' PRECEDING AND CURRENT ROW

# 直前のグループ（同じ値の行の集まり）から現在まで
fn.count().over(order_by=Order.ordered_at, frame=groups_between(-1, 0))
# ... GROUPS BETWEEN 1 PRECEDING AND CURRENT ROW
```

| 関数 | 単位 |
|---|---|
| `rows_between(start, end)` | 行数 |
| `range_between(start, end)` | ORDER BY の値の差（数値や `timedelta`） |
| `groups_between(start, end)` | ORDER BY の値が同じ行のグループ数 |

境界の指定方法は次のとおりです。

| 値 | 意味 |
|---|---|
| `None` | `UNBOUNDED PRECEDING`（開始）/ `UNBOUNDED FOLLOWING`（終了） |
| `0`（または `timedelta(0)`） | `CURRENT ROW` |
| `-n` / `n` | `n PRECEDING` / `n FOLLOWING` |
| `-timedelta(...)` / `timedelta(...)` | `INTERVAL ... PRECEDING` / `FOLLOWING`（`range_between` で使う） |

`exclude=` には `"current row"`、`"group"`、`"ties"`、`"no others"` を指定できます。

### 名前付きウィンドウ

同じウィンドウを何度も使うときは、`.window()` で名前を付けます。

```python
from parrotlet import window

w = window(partition_by=Order.user_id, order_by=Order.amount.desc())
select(
    fn.rank().over("w"),
    fn.sum(Order.amount).over("w"),
).from_(Order).window("w", w)
# SELECT rank() OVER "w", sum("orders"."amount") OVER "w" FROM "orders"
#   WINDOW "w" AS (PARTITION BY "orders"."user_id" ORDER BY "orders"."amount" DESC)
```

名前付きウィンドウにフレームなどを追加することもできます。

```python
fn.sum(Order.amount).over("w", frame=rows_between(None, 0))
# sum("orders"."amount") OVER ("w" ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
```

`window(...)` を `.over()` に直接渡すこともできます。

## QUALIFY

`QUALIFY` は、ウィンドウ関数の結果で行を絞り込みます。サブクエリを使わずに「グループごとの上位 N 件」を書けます。

```python
select(User.name, User.country).from_(User).qualify(
    fn.row_number().over(partition_by=User.country, order_by=User.age.desc()) == 1
)
# SELECT ... FROM "users"
#   QUALIFY (row_number() OVER (
#     PARTITION BY "users"."country" ORDER BY "users"."age" DESC
#   ) = ?)
```

`.qualify()` を複数回呼ぶと、AND で結合されます。
