# 型安全の仕組み

parrotlet の型検査は、すべて静的な型チェッカー（pyright など）が行います。実行時に型を検査するコードはほとんどありません。このページでは、Python の型システムの機能をどう組み合わせて SQL の型規則を表しているかを説明します。使い方としての説明は[ガイドの型安全](../guide/typing.md)を参照してください。

## 型のクラスを幽霊型として使う

`Expr[T]` の `T` には、`type.py` のクラス（`Integer`、`Varchar`、`List[T]` など）が入ります。式の側では、このクラスは型チェッカーに型を伝えるためだけに使われ、式のオブジェクトは `T` の情報を持ちません。このような型パラメータを幽霊型（phantom type）と呼びます。

同じクラスは、値としては DuckDB の型そのものです。引数のない型はクラスのまま（`qlt.Integer`）、引数のある型はインスタンス（`qlt.Decimal(10, 2)`）として渡し、`to_type()` がどちらも SQL の型名を持つインスタンスにそろえます。`cast()` などは `type[U] | U`（`U` は `SqlType` に束縛）を受け取るので、どちらを渡しても `Expr[U]` が返ります。

```python
class SqlType:
    sql_name: ClassVar[str | None] = None  # None は抽象的な型（Numeric など）


class Varchar(SqlType):
    sql_name = "VARCHAR"


class List[T](SqlType):
    def __init__(self, element: type[T] | T) -> None: ...  # 実際は type[T] と T の2つのオーバーロード
```

実行時には、`Expr[Integer]` と `Expr[Varchar]` に違いはありません。どちらも同じ `ColumnRef` や `BinaryOp` のインスタンスで、`T` の情報は持っていません。

## 継承で暗黙の型変換を表す

DuckDB は、`INTEGER` を `BIGINT` や `DOUBLE` が必要な場所に暗黙に変換します。parrotlet は、この規則をクラスの継承で表しています。狭い型が、変換先の広い型を継承します。

```text
Numeric
└── Double
    ├── Float
    └── Decimal
        ├── HugeInt
        │   └── BigInt
        │       └── Integer
        │           └── SmallInt
        │               └── TinyInt
        └── UHugeInt
            └── UBigInt（UHugeInt と HugeInt を継承）
                └── UInteger（UBigInt と BigInt を継承）……

TimestampTz
└── Timestamp
    ├── Date
    └── TimestampS / TimestampMs / TimestampNs

Varchar
├── Json
└── Enum

List[T]
└── Array[T]
```

`Expr[T]` は PEP 695 の構文で宣言されていて、型チェッカーは `T` を共変（covariant）と推論します。そのため `Expr[Integer]` は `Expr[Double]` が必要な場所に渡せます。

```python
age: Expr[t.Integer] = ...
x: Expr[t.Double] = age  # OK：INTEGER は DOUBLE に暗黙に変換される
y: Expr[t.Varchar] = age  # 型エラー
```

型の分からない式（`col("x")` や `func.foo()` など）は `Expr[Any]` で、どの型とも互換です。型付けをあきらめるときは、これを使います。

## 制約付き TypeVar で「比較できる型」を表す

比較演算子は、同じ系統の型どうしでしか使えません。`Integer` と `Double` は比較できますが、`Integer` と `Varchar` は比較できません。これを、制約付き TypeVar で表しています。

```python
_Cmp = TypeVar(
    "_Cmp",
    t.Numeric,
    t.Varchar,
    t.Boolean,
    t.TimestampTz,
    t.TimeTz,
    t.Interval,
    t.Blob,
    t.Uuid,
    t.Bit,
    t.Geometry,
    t.List[Any],
    t.Map[Any, Any],
    t.Struct,
)


def __lt__(self: Expr[_Cmp], other: Expr[_Cmp]) -> Bool: ...
```

制約付き TypeVar は、列挙した型のどれか1つに解決されます（`bound=` と違い、それらの共通の親には広がりません）。

- `Expr[Integer] < Expr[Double]`：両方とも `Numeric` のサブタイプなので、`_Cmp = Numeric` に解決されて OK
- `Expr[Integer] < Expr[Varchar]`：両方を満たす制約がないので型エラー

## `self` の型で絞るオーバーロード

演算子やメソッドは、`self` に型注釈を付けたオーバーロードで定義しています。レシーバーの型によって、使えるかどうかと戻り値の型が決まります。

```python
@overload
def __add__(self: Expr[_N], other: Expr[_N] | int | PyDecimal) -> Expr[_N]: ...
@overload
def __add__(self: Expr[_N], other: Expr[_M]) -> Expr[_M]: ...
@overload
def __add__(self: Expr[t.Numeric], other: float) -> Expr[t.Double]: ...
@overload
def __add__(self: Expr[t.Date], other: Expr[t.Integer] | int) -> Expr[t.Date]: ...
@overload
def __add__(self: Expr[t.Date], other: Expr[t.Interval] | datetime.timedelta) -> Expr[t.Timestamp]: ...


...


def __add__(self, other: object) -> Expr[Any]:
    return BinaryOp(self, "+", to_expr(other))
```

- `Expr[Integer] + 1` は `Expr[Integer]`、`Expr[Integer] + 1.5` は `Expr[Double]`
- `Expr[Date] + 1` は `Expr[Date]`、`Expr[Date] + timedelta(...)` は `Expr[Timestamp]`
- `Expr[Varchar] + 1` は、どのオーバーロードにも当てはまらないので型エラー

実装（オーバーロードではない最後の定義）は1つだけで、どの場合も `BinaryOp` を作るだけです。型の規則はオーバーロードの宣言にだけ書かれています。

同じ方法で、`&` `|` `~` は `Expr[Boolean]` だけ、`.like()` は `Expr[Varchar]` だけ、`xs[1]` はリスト・マップ・構造体・文字列だけで使えるようにしています。`where()` や `having()` の引数も `Expr[Boolean]` なので、`where(User.name)` は型エラーになります。

### `==` と `!=`

`__eq__` は `object.__eq__` をオーバーライドするので、本来は任意の引数を受け付けなければなりません。parrotlet はこの規則を `# pyright: ignore[reportIncompatibleMethodOverride]`（ty では `# ty: ignore[invalid-method-override]`）で意図的に破り、比較できない型の組み合わせを型エラーにしています。`x == None` は `IS NULL` に、`x != None` は `IS NOT NULL` になります。

## Python の値の型

式の相手には Python の値も書けます（`User.age >= 20`）。オーバーロードには、SQL 型ごとに受け付ける Python の型を並べています。

| SQL 型 | 受け付ける Python の値 |
|---|---|
| `Numeric` | `int`、`float`、`Decimal` |
| `Varchar` | `str` |
| `Boolean` | `bool` |
| `TimestampTz`（とそのサブタイプ） | `datetime.date`（`datetime` を含む） |
| `TimeTz` | `datetime.time` |
| `Interval` | `datetime.timedelta` |
| `Blob` / `Uuid` / `Geometry` | `bytes` / `UUID` / shapely のジオメトリ |

`val()` や `lit()` で値を明示的に式にするときも、オーバーロードで Python の型から SQL 型を決めます（`val(1)` は `Param[Integer]`、`val("a")` は `Param[Varchar]`）。

## 結果の型が引数で決まる関数

`coalesce(x, 0)` の結果の型は `x` の型と同じです。引数の型から戻り値の型が決まる関数は、PEP 695 のジェネリック関数として `functions/_generic.py` に手書きしています。

```python
def coalesce[T](first: Expr[T], /, *rest: Expr[T] | PyScalar) -> Func[T]: ...
def max[T](value: Expr[T], /, *, distinct: bool = False, order_by: OrderBy = None) -> AggregateFunc[T]: ...
```

`list_transform(xs, lambda x: x * 2)` のような高階関数では、ラムダの引数にも要素の型が付きます。ラムダの中の `x` は `Expr[E]`（`xs` の要素型）として型検査され、戻り値の型が結果のリストの要素型になります。

その他の約 1,200 個の関数は、DuckDB のカタログから生成したオーバーロードで型付けされています（[関数の生成](functions.md)）。

## モデルのカラムの型

`User.age` の型は、`Column` デスクリプタの `__get__` のオーバーロードで決まります。`Column[int]` や `Column[int | None]` をクラスから参照すると `ColumnRef[BigInt]` に、インスタンスから参照すると `int` や `int | None` になります。詳しくは[モデル](model.md#column-descriptor)を参照してください。

## ステートメントの型

ステートメント自体（`Select` など）は、結果のカラムの型を型パラメータとして持っていません。カラムの数や型を型レベルで追跡すると、SELECT リストの組み合わせごとにオーバーロードが爆発するためです。結果の型は、`fetch_as(User)` や `fetch_as(MyDataclass)` のように、受け取る側の型で指定します。

## 型検査のテスト

型の規則は `tests/typing_checks.py` で検査しています。このファイルは実行せず、pyright と ty にだけかけます。

- `assert_type(...)` で、推論される型を固定する
- 型エラーになるべき行には `# pyright: ignore[...]` と `# ty: ignore[...]` を付ける
- pyright の `reportUnnecessaryTypeIgnoreComment` と ty の `unused-ignore-comment` をエラーにしているので、エラーになるべき行がエラーにならなくなると、不要な ignore として型チェッカーが失敗する

これで、「通るべきものが通る」ことと「通ってはいけないものが通らない」ことの両方をテストしています。
