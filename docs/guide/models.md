# モデル

`Model` のサブクラスは、テーブル定義であると同時に、dataclass のような行の型でもあります。

```python
import datetime
from collections.abc import Sequence
from decimal import Decimal

from parrotlet import Check, Column, Constraint, Model, Unique, column
import parrotlet.type as qlt
import parrotlet.functions as fn
class Product(Model, table="products", schema="main"):
    id: Column[int] = column(primary_key=True)
    sku: Column[str] = column(unique=True, collate="nocase")
    type_: Column[str] = column(name="type", default="normal")
    price: Column[Decimal] = column(qlt.Decimal(10, 2), check=lambda c: c.price >= 0)
    tax: Column[Decimal] = column(
        qlt.Decimal(10, 2),
        generated=lambda c: c.price * Decimal("0.1"),
        init=False,
    )
    serial: Column[int] = column(default=fn.nextval("product_ids"))

    @classmethod
    def constraints(cls) -> Sequence[Constraint]:
        return (Check(fn.length(cls.sku) > 0), Unique(cls.sku, cls.type_))
```

```sql
CREATE TABLE "main"."products" (
  "id" BIGINT PRIMARY KEY,
  "sku" VARCHAR COLLATE "nocase" NOT NULL UNIQUE,
  "type" VARCHAR NOT NULL DEFAULT 'normal',
  "price" DECIMAL(10, 2) NOT NULL CHECK (("price" >= 0)),
  "tax" DECIMAL(10, 2) NOT NULL
    GENERATED ALWAYS AS (("price" * 0.1::DECIMAL)) VIRTUAL,
  "serial" BIGINT NOT NULL DEFAULT nextval('product_ids'),
  CHECK ((length("sku") > 0)),
  UNIQUE ("sku", "type")
)
```

## クラス属性とインスタンス属性

同じ名前の属性が、クラスから参照するかインスタンスから参照するかで、別のものになります。

| 書き方 | 型 | 用途 |
|---|---|---|
| `User.age`（クラス） | `ColumnRef[BigInt]` | クエリの式（`User.age > 20` → `"users"."age" > ?`） |
| `user.age`（インスタンス） | <code>int &#124; None</code> | 行の値 |

```python
user = User(id=1, name="alice")
user.age  # None（値）
User.age  # ColumnRef（"users"."age"）
db.from_(User).where(User.age > 20)  # クエリではクラス属性を使う
```

## インスタンス

```python
u = User(id=1, name="alice")  # キーワード引数のみ
u
# User(id=1, name='alice', age=None, country=None, tags=[],
#      joined=Keyword(keyword='DEFAULT'))
```

- 引数はキーワード引数だけです。型チェッカーは、引数の名前・型・省略できるかどうかを検査します。
- 省略したカラムは既定値になります。`column(default=fn.now())` のような DB 側の既定値を持つカラムは、`DEFAULT` キーワードが入り、INSERT のときにデータベースが値を埋めます。
- 既定値のないカラムを省略すると `TypeError: User() missing keyword argument 'id'` に、知らない引数を渡すと `TypeError: User() got unexpected keyword arguments: foo` になります。
- インスタンスは可変で、`u.age = 31` のように代入できます。そのためハッシュ化はできません。

| メソッド | 戻り値 |
|---|---|
| `u.to_dict()` | `{属性名: 値}` |
| `u.to_row()` | `{SQL のカラム名: 値}`（`column(name=...)` を使ったときに `to_dict()` と違う） |
| `User.from_row({"id": 1, "name": "a"})` | 辞書からインスタンスを作る。足りないカラムは `None` |
| `u == other` | 同じクラスで、すべての値が等しければ `True` |

## カラムの宣言

`name: Column[T]` で宣言します。オプションを付けるときは `= column(...)` を使います。

```python
class User(Model, table="users"):
    id: Column[int] = column(primary_key=True)  # オプション付き
    name: Column[str]  # オプションなし（必須の NOT NULL カラム）
```

### `column()` の引数

| 引数 | 意味 | 生成される SQL の例 |
|---|---|---|
| `sql_type` | DuckDB の型。省略するとアノテーションから推論 | `column(qlt.Decimal(10, 2))` → `DECIMAL(10, 2)` |
| `name` | SQL のカラム名（属性名と違うとき） | `type_: Column[str] = column(name="type")` → `"type"` |
| `primary_key` | 主キー | `PRIMARY KEY`（`NOT NULL` は付けない） |
| `unique` | 一意制約 | `UNIQUE` |
| `nullable` | <code>X &#124; None</code> から推論される NULL 許可を上書き | `nullable=True` で `NOT NULL` を外す |
| `default` | Python 側の既定値。SQL の `DEFAULT` にもなる | `default="pending"` → `DEFAULT 'pending'` |
| `default_factory` | Python 側の既定値のファクトリ。SQL の `DEFAULT` にはならない | `default_factory=list` |
| `server_default` | SQL 側だけの既定値（通常は `default=<式>` を使う） | `server_default=0` → `DEFAULT 0` |
| `check` | カラムの CHECK 制約。式、または `lambda cls: ...` | `check=lambda c: c.price >= 0` → `CHECK (("price" >= 0))` |
| `references` | 外部キー | `references=User.id` → `REFERENCES "users" ("id")` |
| `generated` | 生成カラム。式、または `lambda cls: ...` | `GENERATED ALWAYS AS (...) VIRTUAL` |
| `collate` | 照合順序 | `collate="nocase"` → `COLLATE "nocase"` |
| `init` | `False` にするとコンストラクタの引数に含めない | 生成カラムなどに使う |

### 既定値の種類

既定値の書き方によって、Python 側と SQL 側の動作が変わります。

| 書き方 | コンストラクタで省略したとき | SQL の `DEFAULT` |
|---|---|---|
| `column(default=0)` | `0` | `DEFAULT 0` |
| `column(default=None)` | `None` | なし（NULL 許可のカラムで使う） |
| `column(default_factory=list)` | `[]`（毎回新しいリスト） | なし |
| `column(default=fn.now())`（SQL の式） | `DEFAULT` キーワード | `DEFAULT get_current_timestamp()` |
| `column(default=fn.nextval("seq"))` | `DEFAULT` キーワード | `DEFAULT nextval('seq')` |
| `column(server_default=0)` | `DEFAULT` キーワード | `DEFAULT 0` |

!!! note "既定値は `column(default=...)` で書く"
    `age: Column[int | None] = None` のように素の値を書いても、実行時には動きます。ただし型チェッカーは、`Column[...]` 型の属性に `None` を代入しているとみなしてエラーにします。既定値は `column(default=None)` と書いてください。

!!! note "可変な既定値"
    リストや辞書の既定値は、`column(default=[])` ではなく `column(default_factory=list)` と書いてください。`default=[]` は全インスタンスで同じリストを共有します。

### CHECK と生成カラムのラムダ

`check` と `generated` にラムダを渡すと、ラムダの引数にモデルのクラスが渡されます。クラスの定義が終わってから評価されるので、同じクラスの他のカラムを参照できます。

```python
class Rect(Model):
    w: Column[float] = column(check=lambda c: c.w > 0)
    h: Column[float]
    area: Column[float] = column(generated=lambda c: c.w * c.h, init=False)
```

```sql
CREATE TABLE "rect" (
  "w" DOUBLE NOT NULL CHECK (("w" > 0)),
  "h" DOUBLE NOT NULL,
  "area" DOUBLE NOT NULL GENERATED ALWAYS AS (("w" * "h")) VIRTUAL
)
```

CHECK や生成カラムの式の中では、カラム名はテーブル名なしで出力され、値はパラメータではなく、リテラルとして埋め込まれます。DuckDB の DDL がパラメータを受け付けないためです。

生成カラムには値を入れられないので、`init=False` にしてコンストラクタの引数から外してください。appender は生成カラムを自動で除きます。

### 型の推論

| Python の型 | DuckDB の型 | クエリでの型（`Model.col`） |
|---|---|---|
| `bool` | `BOOLEAN` | `ColumnRef[Boolean]` |
| `int` | `BIGINT` | `ColumnRef[BigInt]` |
| `float` | `DOUBLE` | `ColumnRef[Double]` |
| `Decimal` | `DECIMAL(18, 3)` | `ColumnRef[Decimal]` |
| `str` | `VARCHAR` | `ColumnRef[Varchar]` |
| `bytes` | `BLOB` | `ColumnRef[Blob]` |
| `UUID` | `UUID` | `ColumnRef[Uuid]` |
| `datetime.datetime` | `TIMESTAMP` | `ColumnRef[Timestamp]` |
| `datetime.date` | `DATE` | `ColumnRef[Date]` |
| `datetime.time` | `TIME` | `ColumnRef[Time]` |
| `datetime.timedelta` | `INTERVAL` | `ColumnRef[Interval]` |
| shapely のジオメトリ（`BaseGeometry`、`Point` など） | `GEOMETRY` | `ColumnRef[Geometry]` |
| `list[str]` / `list[int]` / `list[float]` / `list[bool]` | `VARCHAR[]` など | `ColumnRef[List[Varchar]]` など |
| その他の `list[X]` | `X[]` | `ColumnRef[Any]` |
| `dict[K, V]` | `MAP(K, V)` | `ColumnRef[Any]` |

- `X | None` は NULL を許可し、それ以外は `NOT NULL` になります。
- 推論できない型（構造体など）は、`column(qlt.Struct(...))` のように明示してください。推論できない型を書くと、クラスを定義した時点で `TypeError` になります。
- 型を明示しても、クエリでの型（`ColumnRef[...]`）は Python のアノテーションから決まります。`Column[int] = column(qlt.Integer)` はテーブル上は `INTEGER` ですが、クエリでは `ColumnRef[BigInt]` です。

使える型の一覧は[データ型](datatypes.md)を参照してください。

## テーブルのオプション

クラスキーワードで指定します。

```python
class User(Model, table="users", schema="main"): ...
```

| キーワード | 意味 |
|---|---|
| `table` | テーブル名。省略するとクラス名の snake_case（`OrderLine` → `order_line`） |
| `schema` | スキーマ名 |
| `abstract` | `True` にするとテーブルを持たない（共通カラムの定義用） |

## テーブル制約

複数のカラムにまたがる制約は、`constraints` クラスメソッドで宣言します。クラスの定義が終わってから呼ばれるので、`cls.<カラム>` を使えます。

```python
from parrotlet import ForeignKey, PrimaryKey


class OrderLine(Model):
    order_id: Column[int]
    line_no: Column[int]
    sku: Column[str]

    @classmethod
    def constraints(cls) -> Sequence[Constraint]:
        return (
            PrimaryKey(cls.order_id, cls.line_no),
            ForeignKey(cls.order_id, Order.id),
            ForeignKey([cls.sku], "products"),
        )
```

```sql
CREATE TABLE "order_line" (
  "order_id" BIGINT NOT NULL,
  "line_no" BIGINT NOT NULL,
  "sku" VARCHAR NOT NULL,
  PRIMARY KEY ("order_id", "line_no"),
  FOREIGN KEY ("order_id") REFERENCES "orders" ("id"),
  FOREIGN KEY ("sku") REFERENCES "products"
)
```

| 制約 | 書き方 |
|---|---|
| 複合主キー | `PrimaryKey(cls.a, cls.b)` |
| 複合一意制約 | `Unique(cls.a, cls.b)` |
| テーブルの CHECK | `Check(cls.start < cls.end)` |
| 外部キー | `ForeignKey(cls.a, Other.id)`、`ForeignKey([cls.a, cls.b], [Other.x, Other.y])`、`ForeignKey(cls.a, "other")` |

カラムには、`cls.a` のほかにカラム名の文字列（`"a"`）も使えます。

外部キーの参照先（`references=` と `ForeignKey` の第2引数）は、次のどれでも書けます。

| 参照先 | SQL |
|---|---|
| `User.id` | `REFERENCES "users" ("id")` |
| `"users.id"` | `REFERENCES "users" ("id")` |
| `User` または `"users"` | `REFERENCES "users"`（主キーを参照） |

`constraints` というカラム名は、このクラスメソッドと衝突するので使えません。`constraints_: Column[str] = column(name="constraints")` のように別名を付けてください。

## 継承

共通のカラムは、`abstract=True` のモデルにまとめて継承できます。

```python
class Base(Model, abstract=True):
    id: Column[int] = column(primary_key=True)
    created_at: Column[datetime.datetime] = column(default=fn.now())


class Tag(Base):
    label: Column[str]
```

```sql
CREATE TABLE "tag" (
  "id" BIGINT PRIMARY KEY,
  "created_at" TIMESTAMP NOT NULL DEFAULT get_current_timestamp(),
  "label" VARCHAR NOT NULL
)
```

- 親のカラムは、子のカラムより前に並びます。
- 具象モデルを継承すると、親のテーブル名と schema を引き継ぎます（別のテーブルにするときは `table=` を指定します）。
- 制約を継承するときは、`constraints` の中で `super().constraints()` を呼んでください。
- `Column` 属性を持つだけの普通のクラスを mixin として継承することもできます。

## CREATE TABLE

```python
from parrotlet import create_table

create_table(User)  # CREATE TABLE "users" (...)
create_table(User).if_not_exists()  # CREATE TABLE IF NOT EXISTS
create_table(User).or_replace()  # CREATE OR REPLACE TABLE
create_table(User).temporary()  # CREATE TEMPORARY TABLE
db.register(User)  # Database を使う場合（IF NOT EXISTS で即実行）
```

クエリの結果からテーブルを作るときは、テーブル名と `.as_()` を使います。

```python
q = select(User.country, fn.count().as_("n")).from_(User).group_by(User.country)
create_table("summary").as_(q)
# CREATE TABLE "summary" AS
#   SELECT "users"."country", count(*) AS "n" FROM "users"
#   GROUP BY "users"."country"
```

既存のテーブルを変更するときは [ALTER TABLE](ddl.md#alter-table) を使います。

## テーブル参照

テーブル単位の操作は `table(Model)` で行います。

```python
from parrotlet import table

table(User).star(exclude=["tags"])  # "users".* EXCLUDE ("tags")
table(User).as_("u")  # 別名付きの参照
table(User, alias="u")  # 同じ
table(User).tablesample(percent=10)  # TABLESAMPLE
table(User).name  # "users"
```

別名を付けたテーブルのカラムは、`.c.<名前>` で参照します（型なし）。

```python
u = table(User, alias="u")
select(u.c.name).from_(u)  # SELECT "u"."name" FROM "users" AS "u"
```

型付きのまま別名を付けたいときは、次の `aliased()` を使います。

## 自己結合と別名 {#aliased}

```python
from parrotlet import aliased

Boss = aliased(User, "boss")
select(User.name, Boss.name.as_("boss")).from_(User).join(Boss, User.id == Boss.id)
```

```sql
SELECT "users"."name", "boss"."name" AS "boss"
FROM "users" INNER JOIN "users" AS "boss" ON ("users"."id" = "boss"."id")
```

`aliased()` が返すクラスでは、カラムが別名で修飾されます。カラムの型も元のモデルと同じなので、型チェックもできます。同じテーブルを2回以上 FROM / JOIN に書くときに使います。
