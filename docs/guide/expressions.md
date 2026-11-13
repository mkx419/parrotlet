# 式

## 値とカラム

```python
from parrotlet import col, lit, sql, table, val

User.name  # モデルのカラム（型付き）
table("t").c.name  # テーブルのカラム（型なし）
col("name")
col("name", "t")
val(1)  # パラメータ（?）
lit("x")  # インラインのリテラル
sql(t"date_trunc('day', {User.joined})")  # 生の SQL（埋め込んだ値はパラメータ）
```

Python の値はパラメータとしてバインドされます。カラムを並べる場所（`select` / `group_by` / `order_by` / `returning` など）では、`str` はカラム名として扱われます（`"*"` は `*`）。

## 演算子とメソッド

| Python | SQL |
|---|---|
| `==` `!=` `<` `<=` `>` `>=` | 比較（`== None` は `IS NULL`） |
| `&` `\|` `~` | `AND` / `OR` / `NOT` |
| `+` `-` `*` `/` `//` `%` `**` | 算術演算（数値・日付時刻・INTERVAL） |
| `x[1]`、`x[1:3]`、`x[1:5:2]`、`x[-1]`、`x["field"]` | リスト・文字列・MAP・構造体のインデックス |
| `.in_([...])` / `.in_(subquery)` / `.not_in(...)` | `IN` |
| `.between(a, b)` / `.not_between(a, b)` | `BETWEEN` |
| `.like` / `.ilike` / `.not_like` / `.not_ilike` / `.glob` / `.similar_to` | パターンマッチ |
| `.is_null()` / `.is_not_null()` / `.is_distinct_from(x)` | NULL 判定 |
| `.is_true()` / `.is_false()` / `.is_not_true()` / `.is_not_false()` | 真偽判定 |
| `.cast(dt.X)` / `.try_cast(dt.X)` | `CAST` / `TRY_CAST` |
| `.concat(x)` | `\|\|` |
| `.collate("nocase")` | `COLLATE` |
| `.at_time_zone("Asia/Tokyo")` | `AT TIME ZONE` |
| `.json_get(path)` / `.json_get_text(path)` | `->` / `->>` |
| `.has_all(xs)` / `.contained_by(xs)` / `.has_any(xs)` | `@>` / `<@` / `&&` |
| `.as_("alias")` / `.asc(nulls="first")` / `.desc()` | 別名・並び順 |

## 論理演算

```python
from parrotlet import and_, exists, not_, not_exists, or_

and_(User.age > 20, User.name.like("a%"))
or_(...)
not_(...)
exists(select(1).from_(Order).where(Order.customer_id == Customer.id))
```

## CASE

```python
from parrotlet import case

case().when(User.age < 20, "minor").when(User.age < 65, "adult").else_("senior")  # SearchedCase[Varchar]
case(User.country).when("JP", "Japan").else_("other")  # SimpleCase[...]
```

最初の THEN の型が、CASE 全体の型になります。

## 量化子・TRY・位置参照

```python
from parrotlet import all_, any_, positional, try_

User.age > all_(select(F.avg(User.age)).from_(User))
User.name == any_(Team.members)  # リストのどれかと等しい
try_(val("x").cast(dt.INTEGER))  # TRY(...)：エラーの代わりに NULL
positional(1)  # #1
```

## ラムダとリスト内包表記

Python のラムダは DuckDB のラムダになります。引数の型も推論されます。

```python
F.list_transform(User.tags, lambda t: F.upper(t))
F.list_filter(User.scores, lambda s: s > 50)
F.list_reduce(User.scores, lambda acc, s: acc + s)
F.list_transform(User.tags, lambda t, i: F.concat(i, ":", t))  # 2つ目の引数は 1 始まりのインデックス

from parrotlet import list_comprehension

list_comprehension(User.scores, lambda s: s * 2, where=lambda s: s > 50)
# [s * 2 FOR s IN scores IF s > 50]
```

## ウィンドウ関数

```python
from parrotlet import range_between, rows_between, window

F.row_number().over(partition_by=User.country, order_by=User.age.desc())
F.sum(Order.amount).over(order_by=Order.ordered_at, frame=rows_between(None, 0))
F.sum(Order.amount).over(order_by=Order.ordered_at, frame=range_between(-timedelta(days=7), 0))
F.sum(x).over(order_by=y, frame=rows_between(None, None, exclude="current row"))
F.lag(User.name, 1, "none").over(order_by=User.id)
F.first_value(User.name, order_by=User.age, ignore_nulls=True).over()

# 名前付きウィンドウ
select(F.rank().over("w")).from_(User).window("w", window(order_by=User.age))
```

フレームの境界は、`None`（UNBOUNDED）、`0`（CURRENT ROW）、`-n` / `n`（n PRECEDING / FOLLOWING）、`timedelta` で指定します。

集約関数では、`distinct=`、`order_by=`、`.filter(...)`、`.over(...)` が使えます。

```python
F.count(User.country, distinct=True)
F.string_agg(User.name, ",", order_by=User.name)
F.count().filter(User.age >= 20)
```
