# SELECT

ビルダーはイミュータブルです。メソッドは常に新しいオブジェクトを返します。

```python
from parrotlet import from_, select

select(User.id, User.name).from_(User)
select().from_(User)  # SELECT *
select(User).from_(User)  # SELECT "users".*
from_(User)  # DuckDB の FROM 先頭構文
select(User.country).distinct()
select(User.country, User.name).distinct(on=User.country)
```

## FROM と JOIN

```python
select(...).from_(User).join(Order, User.id == Order.customer_id)
# join / left_join / right_join / full_join / cross_join / natural_join
# semi_join / anti_join / asof_join(target, on) / positional_join
select(...).from_(table("a")).join(table("b"), using="id")
```

FROM には次のものを渡せます。

| 渡すもの | 例 |
|---|---|
| モデル、テーブル名 | `User`、`table(User).as_("u")`、`"users"`、`table("t", schema="s")` |
| 別名と列の別名 | `table("t").as_("x", ["c1", "c2"])` |
| サブクエリ | `select(...).subquery("s")`、`.subquery("s", lateral=True)` |
| CTE | `q.cte("c")` を `.with_(cte)` と組み合わせる |
| テーブル関数 | `TF.read_parquet("x.parquet").as_("p")`、`TF.range(10)` |
| VALUES | `values((1, "a"), (2, "b"), alias="v", columns=["k", "s"])` |
| ファイル | `file("data/*.parquet").as_("f")` |
| サンプリング | `tablesample(User, percent=10)`、`table("t").tablesample(rows=100, method="reservoir", seed=1)` |

## WHERE / GROUP BY / HAVING / QUALIFY

```python
select(User.country, F.count()).from_(User).where(User.age > 20).where(User.name.like("a%"))   # AND で結合
    .group_by(User.country).having(F.count() > 1)

select(...).group_by_all()
select(...).group_by(rollup(User.country, User.city))    # cube / grouping_sets
select(User.name).from_(User).qualify(F.row_number().over(partition_by=User.country, order_by=User.age) == 1)
```

## ORDER BY / LIMIT

```python
.order_by(User.age.desc(nulls="last"), User.name)
.order_by_all(desc=True)
.limit(10, offset=20)
.limit(10, percent=True)        # LIMIT 10%
.using_sample(percent=10, method="bernoulli", seed=42)
```

## サブクエリ・CTE・集合演算

```python
totals = select(Order.customer_id, F.sum(Order.amount).as_("total")).from_(Order).group_by(Order.customer_id)
t = totals.subquery("t")
select(Customer.name, t.c.total).from_(Customer).join(t, Customer.id == t.c.customer_id)

select(User.name).from_(User).where(User.age > select(F.avg(User.age)).from_(User).scalar())  # スカラーサブクエリ

recent = select(Order).from_(Order).where(Order.ordered_at > cutoff).cte("recent")
select(F.count()).with_(recent).from_(recent)
# 再帰 CTE: q.cte("r", columns=[...], using_key=["k"]) と .with_recursive(cte)

q1.union(q2)
q1.union_all(q2)
q1.union(q2, by_name=True)
q1.intersect(q2)
q1.except_(q2)
```

## PIVOT / UNPIVOT

単独の文として実行できるほか、`.subquery()` で FROM にも使えます。

```python
from parrotlet import pivot, unpivot

pivot(Sales).on(Sales.month, values=["jan", "feb"]).using(F.sum(Sales.amount).as_("total")).group_by(Sales.region)
unpivot(Wide).on(columns("m_.*")).into(name="month", value="amount")
```

`values=` を省略すると、DuckDB が値を自動で列挙します。この場合は DuckDB の都合でパラメータを使えないため、値をインライン展開して自動で再実行します。

## SQL の確認

```python
q.sql  # パラメータ（?）付きの SQL
q.params  # パラメータの値
q.sql_inline  # 値をリテラルとして展開した SQL（デバッグ用）
```
