# はじめに

## データベースとモデル

```python
import datetime
from decimal import Decimal

from parrotlet import Column, Database, Model, column
from parrotlet import functions as F

db = Database("shop.duckdb")  # Database() ならインメモリ


@db.register
class Customer(Model, table="customers"):
    id: Column[int] = column(primary_key=True)
    name: Column[str]
    country: Column[str | None] = column(default=None)


@db.register
class Order(Model, table="orders"):
    id: Column[int] = column(primary_key=True)
    customer_id: Column[int] = column(references=Customer.id)
    amount: Column[Decimal]
    ordered_at: Column[datetime.datetime] = column(default=F.now())
```

`@db.register` を付けると、その場で `CREATE TABLE IF NOT EXISTS` が実行されます。カラムの SQL 型はアノテーションから推論されます（`int` → `BIGINT`、`str` → `VARCHAR`、`Decimal` → `DECIMAL(18, 3)` など）。`X | None` は NULL を許可し、それ以外は `NOT NULL` になります。

## 行の追加と取得

```python
db.insert(Customer).values(Customer(id=1, name="alice", country="JP"), Customer(id=2, name="bob")).execute()

with db.appender(Order) as app:  # 大量の行は appender で
    app.append(Order(id=10, customer_id=1, amount=Decimal("120.00")))
    app.append(Order(id=11, customer_id=1, amount=Decimal("30.50")))

db.from_(Customer).where(Customer.id == 1).fetch(Customer)  # [Customer(id=1, name='alice', country='JP')]
```

## クエリ

```python
q = (
    db.select(Customer.name, F.sum(Order.amount).as_("total"))
    .from_(Customer)
    .join(Order, Customer.id == Order.customer_id)
    .where(Order.ordered_at >= datetime.datetime(2026, 1, 1))
    .group_by(Customer.name)
    .order_by(F.sum(Order.amount).desc())
)

q.sql  # 'SELECT "customers"."name", sum("orders"."amount") AS "total" FROM "customers" INNER JOIN ...'
q.params  # (datetime.datetime(2026, 1, 1, 0, 0),)
q.fetchall()  # [('alice', Decimal('150.50'))]
q.df()  # pandas DataFrame
```

結果をデータクラスに変換することもできます。

```python
from dataclasses import dataclass


@dataclass
class Total:
    name: str
    total: Decimal


q.fetch(Total)  # [Total(name='alice', total=Decimal('150.50'))]
```

## Database を使わない場合

ステートメントは単独でも組み立てられます。`execute(con)` に DuckDB の接続を渡すか、省略すると DuckDB のデフォルト接続で実行されます。

```python
import duckdb
from parrotlet import select, table

con = duckdb.connect()
t = table("events")
select(t.c.kind, F.count()).from_(t).group_by(t.c.kind).execute(con).fetchall()
```
