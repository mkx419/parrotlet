# はじめに

このページでは、parrotlet をインストールして、テーブルを作り、行を入れ、クエリを書いて結果を受け取るまでを順に説明します。

## インストール

```bash
uv add parrotlet
```

Python 3.14 以上が必要です。依存パッケージは `duckdb`（2.0 以上）と `shapely` です。`.df()` で pandas の DataFrame を、`.pl()` で polars の DataFrame を受け取る場合は、それぞれのパッケージを別にインストールしてください。

型安全の恩恵を受けるには、エディタやCIで pyright などの型チェッカーを使ってください。parrotlet は `py.typed` を含んでいます。

## インポートの慣例

```python
import parrotlet as ql
import parrotlet.type as qlt
import parrotlet.functions as fn
```

| インポート | 内容 |
|---|---|
| `ql` | パッケージ直下のもの（`ql.select`、`ql.Model`、`ql.Database` など） |
| `qlt` | DuckDB の型（`qlt.Integer`、`qlt.Decimal(10, 2)` など） |
| `fn` | 型付きの DuckDB 関数（`fn.upper`、`fn.sum` など） |
| `fn.spatial` | spatial 拡張の関数（`fn.spatial.st_distance` など） |
| `fn.table` | テーブル関数（`fn.table.read_parquet` など） |

別名はどれも PEP 8 に合わせて小文字にしています。パッケージ直下のものは `from parrotlet import select, Model` のように個別に import することもでき、このガイドの例はおもにこの書き方を使います。

`fn.sum` や `fn.max` のように Python の組み込み関数と同じ名前があるので、`from parrotlet.functions import *` は避けてください。

## データベースを開く

```python
db = Database("shop.duckdb")  # ファイル。Database() ならインメモリ
```

`Database` は DuckDB の接続を1つ持ちます。`db.select(...)` のように `db` から作ったステートメントは、その接続で実行されます（[Database](database.md)）。

## このガイドで使うモデル {#sample-models}

ガイドのほとんどの例は、次の2つのモデルを使います。

```python
import datetime
from decimal import Decimal


@db.register
class User(Model, table="users"):
    id: Column[int] = column(primary_key=True)
    name: Column[str]
    age: Column[int | None] = column(default=None)
    country: Column[str | None] = column(default=None)
    tags: Column[list[str]] = column(default_factory=list)
    joined: Column[datetime.datetime] = column(default=fn.now())


@db.register
class Order(Model, table="orders"):
    id: Column[int] = column(primary_key=True)
    user_id: Column[int] = column(references=User.id)
    amount: Column[Decimal]
    status: Column[str] = column(default="pending")
    ordered_at: Column[datetime.datetime] = column(default=fn.now())
```

`@db.register` は、その場で `CREATE TABLE IF NOT EXISTS` を実行します。生成される SQL は次のとおりです。

```sql
CREATE TABLE IF NOT EXISTS "users" (
  "id" BIGINT PRIMARY KEY,
  "name" VARCHAR NOT NULL,
  "age" BIGINT,
  "country" VARCHAR,
  "tags" VARCHAR[] NOT NULL,
  "joined" TIMESTAMP NOT NULL DEFAULT get_current_timestamp()
)
CREATE TABLE IF NOT EXISTS "orders" (
  "id" BIGINT PRIMARY KEY,
  "user_id" BIGINT NOT NULL REFERENCES "users" ("id"),
  "amount" DECIMAL(18, 3) NOT NULL,
  "status" VARCHAR NOT NULL DEFAULT 'pending',
  "ordered_at" TIMESTAMP NOT NULL DEFAULT get_current_timestamp()
)
```

モデルの書き方と SQL は、次のように対応します。

- カラムの SQL 型はアノテーションから推論されます（`int` → `BIGINT`、`str` → `VARCHAR`、`list[str]` → `VARCHAR[]`、`Decimal` → `DECIMAL(18, 3)`）。
- `X | None` は NULL を許可し、それ以外は `NOT NULL` になります。
- `column(default="pending")` は、Python のコンストラクタの既定値であり、SQL の `DEFAULT` にもなります。
- `column(default=fn.now())` のように SQL の式を既定値にすると、データベース側で値が埋められます。

詳しくは[モデル](models.md)を参照してください。

## 行を追加する

モデルのクラスは、そのまま行の型としても使えます。

```python
alice = User(id=1, name="alice", age=30, country="JP")
bob = User(id=2, name="bob")  # 省略したカラムは既定値になる

db.insert(User).values(alice, bob).execute()
```

```sql
INSERT INTO "users" ("id", "name", "age", "country", "tags", "joined")
VALUES (?, ?, ?, ?, ?, DEFAULT), (?, ?, ?, ?, ?, DEFAULT)
-- params: (1, 'alice', 30, 'JP', [], 2, 'bob', None, None, [])
```

値はすべて `?` パラメータとして DuckDB に渡されます。`joined` は値を省略したので `DEFAULT` になり、データベースが現在時刻を入れます。

大量の行は、INSERT より高速な appender で書き込みます。

```python
with db.appender(Order) as app:
    app.append(Order(id=10, user_id=1, amount=Decimal("120.00")))
    app.extend(Order(id=i, user_id=2, amount=Decimal(i)) for i in range(11, 10_000))
```

## クエリを書く

クラス属性（`User.age`）はクエリで使う型付きのカラムです。Python の演算子で条件を書きます。

```python
q = (
    db.select(User.name, fn.sum(Order.amount).as_("total"))
    .from_(User)
    .join(Order, User.id == Order.user_id)
    .where(
        Order.ordered_at >= datetime.datetime(2026, 1, 1),
        Order.status != "cancelled",
    )
    .group_by(User.name)
    .order_by(fn.sum(Order.amount).desc())
    .limit(10)
)
```

```sql
SELECT "users"."name", sum("orders"."amount") AS "total"
FROM "users" INNER JOIN "orders" ON ("users"."id" = "orders"."user_id")
WHERE (("orders"."ordered_at" >= ?) AND ("orders"."status" <> ?))
GROUP BY "users"."name"
ORDER BY sum("orders"."amount") DESC
LIMIT ?
```

組み立てたクエリは、実行する前に確認できます。

```python
q.sql  # パラメータ（?）付きの SQL
q.params  # (datetime.datetime(2026, 1, 1, 0, 0), 'cancelled', 10)
q.sql_inline  # 値をリテラルとして埋め込んだ SQL（ログやデバッグ用）
```

ビルダーは不変です。`.where()` などのメソッドは元のオブジェクトを変えずに新しいオブジェクトを返すので、途中まで組み立てたクエリを安全に使い回せます。

```python
paid = db.from_(Order).where(Order.status == "paid")
big = paid.where(Order.amount > 1000)  # paid は変わらない
recent = paid.order_by(Order.ordered_at.desc()).limit(20)
```

## 結果を受け取る

```python
q.fetchall()  # [('alice', Decimal('120.000')), ...]（タプルのリスト）
q.fetchone()  # 最初の1行（なければ None）
db.from_(User).where(User.id == 1).fetch_as(User)  # [User(id=1, name='alice', ...)]
db.from_(User).where(User.id == 1).fetch_one_as(User)  # User または None
```

任意のデータクラスにも変換できます。カラム名とフィールド名で対応付けます。

```python
from dataclasses import dataclass


@dataclass
class Total:
    name: str
    total: Decimal


q.fetch_as(Total)  # [Total(name='alice', total=Decimal('120.000')), ...]
```

詳しくは[結果の変換](results.md)を参照してください。

## 型チェッカーが見つけてくれるもの

型チェッカーを使うと、次のような間違いを実行する前に見つけられます。

```python
User.name > 3  # VARCHAR と数値は比較できない
fn.upper(User.age)  # upper は VARCHAR を取る
db.from_(User).where(User.name)  # WHERE には BOOLEAN の式が必要
User(id="1", name="a")  # id は int
User(id=1)  # name が足りない
```

詳しくは[型安全](typing.md)を参照してください。

## Database を使わない場合

ステートメントは `Database` なしでも組み立てられます。実行するときは DuckDB の接続を渡すか、省略して DuckDB のデフォルト接続を使います。

```python
import duckdb
from parrotlet import select, table

con = duckdb.connect()
events = table("events")  # モデルのないテーブル（カラムは型なし）
q = select(events.c.kind, fn.count()).from_(events).group_by(events.c.kind)
q.execute(con).fetchall()
```

## 次に読むもの

- [Database](database.md)：接続、実行、トランザクション、appender
- [モデル](models.md)：カラムのオプション、制約、継承
- [式](expressions.md) と [SELECT](select.md)：クエリの書き方
- [レシピ集](recipes.md)：よくある処理の書き方
