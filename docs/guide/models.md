# モデル

`Model` のサブクラスは、テーブル定義であると同時に、dataclass ライクな行型でもあります。

```python
import datetime
from collections.abc import Sequence
from decimal import Decimal

from shapely.geometry.base import BaseGeometry

from parrotlet import Check, Column, Constraint, Model, Unique, column
from parrotlet import datatype as dt
from parrotlet import functions as F


class Product(Model, table="products", schema="main"):
    id: Column[int] = column(primary_key=True)
    name: Column[str] = column(unique=True)
    price: Column[Decimal] = column(dt.DECIMAL(10, 2), default=Decimal(0), check=lambda c: c.price >= 0)
    tags: Column[list[str]] = column(default_factory=list)
    location: Column[BaseGeometry | None] = column(default=None)
    created_at: Column[datetime.datetime] = column(default=F.now())

    @classmethod
    def constraints(cls) -> Sequence[Constraint]:
        return (Check(F.length(cls.name) > 0),)
```

## クラス属性とインスタンス属性

| 書き方 | 型 | 用途 |
|---|---|---|
| `Product.price` | `ColumnRef[Decimal]` | クエリ（`Product.price > 100`） |
| `p.price`（`p = Product(...)`） | `Decimal` | 行の値 |

```python
p = Product(id=1, name="pen", price=Decimal("1.20"))  # キーワード引数のみ。引数は型チェックされる
p.price  # Decimal('1.20')
p.to_dict()  # {'id': 1, 'name': 'pen', ...}（属性名がキー）
p.to_row()  # SQL のカラム名がキー（INSERT 用）
p == Product(id=1, name="pen", price=Decimal("1.20"))  # 値で比較
```

## カラムの宣言

`name: Column[T]` で宣言します。オプションを付けるときは `= column(...)` を使います。

| `column()` の引数 | 意味 |
|---|---|
| `sql_type` | DuckDB の型（例 `dt.INTEGER`）。省略するとアノテーションから推論 |
| `name` | SQL のカラム名（属性名と違うとき。例 `type_: Column[str] = column(name="type")`） |
| `primary_key` / `unique` | 制約 |
| `nullable` | `X \| None` から推論される NULL 許可を上書き |
| `default` | コンストラクタの既定値で、SQL の `DEFAULT` にもなる。SQL の式（`F.now()`、`F.nextval("seq")`）を渡すと DB 側の既定値になり、値を省略したインスタンスは `DEFAULT` で INSERT される |
| `default_factory` | Python 側の既定値のファクトリ（例 `list`） |
| `check` | カラムの `CHECK`。式、または `lambda cls: cls.price >= 0`（クラスの定義後に評価） |
| `references` | 外部キー（`User.id`、`"users.id"`、`User`） |
| `generated` | `GENERATED ALWAYS AS (...) VIRTUAL`。式またはラムダ |
| `collate` | 照合順序 |
| `init` | `False` にするとコンストラクタの引数に含めない（既定値が必要） |

!!! note "既定値は `column(default=...)` で書く"
    `age: Column[int | None] = None` のように素の値を書いても、実行時には動きます。ただし型チェッカーは `Column[...]` 型の属性に `None` を代入しているとみなし、エラーにします。既定値は `column(default=None)` と書いてください。

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
| `datetime.date` / `datetime` / `time` / `timedelta` | `DATE` / `TIMESTAMP` / `TIME` / `INTERVAL` | 対応する型 |
| shapely のジオメトリ | `GEOMETRY` | `ColumnRef[Geometry]` |
| `list[X]` | `X[]` | `ColumnRef[List[...]]` |
| `dict[K, V]` | `MAP(K, V)` | `ColumnRef[Any]` |

推論できない型の場合は、`column(dt.STRUCT(...))` のように明示してください。

## テーブルのオプション

クラスキーワードで指定します。

```python
class User(Model, table="users", schema="main"): ...


class Base(Model, abstract=True): ...  # 共通カラム用。テーブルにはならない
```

- `table` を省略すると、クラス名の snake_case になります（`OrderLine` → `order_line`）。具象モデルを継承した場合は、親のテーブル名と schema を引き継ぎます。
- `Column` を持つだけの普通のクラスを mixin として継承することもできます。

## テーブル制約

`constraints` クラスメソッドで宣言します。`__post_init__` のようにクラスの定義が終わってから呼ばれるので、`cls.<カラム>` を使えます。

```python
@classmethod
def constraints(cls) -> Sequence[Constraint]:
    return (
        PrimaryKey(cls.a, cls.b),
        Unique(cls.email),
        Check(cls.start < cls.end),
        ForeignKey(cls.user_id, User.id),
    )
```

継承したモデルでは、`super().constraints()` で親の制約を引き継げます。

## CREATE TABLE

```python
from parrotlet import create_table

create_table(Product).if_not_exists()  # or_replace() / temporary()
db.register(Product)  # Database を使う場合
create_table("summary").as_(select(...))  # CREATE TABLE ... AS SELECT
```

## テーブル参照

テーブル単位の操作は `table(Model)` で行います（`__table__` などの内部属性を触る必要はありません）。

```python
from parrotlet import table

table(User).star(exclude=["password"])  # "users".* EXCLUDE ("password")
table(User).as_("u")  # 別名付きの参照（u.c.name でカラム参照）
table(User).tablesample(percent=10)  # TABLESAMPLE
table(User).name  # "users"
table(User, alias="u")  # table(User).as_("u") と同じ
```

## 自己結合

```python
from parrotlet import aliased

Boss = aliased(Employee, "boss")
select(Employee.name, Boss.name).from_(Employee).join(Boss, Employee.boss_id == Boss.id)
```
