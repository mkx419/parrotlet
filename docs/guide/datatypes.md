# データ型

`parrotlet.type` には、DuckDB の型を表すクラスが用意されています。モデルのカラムの型、`CAST`、`ALTER TABLE`、`CREATE TYPE` などで使います。

```python
import parrotlet.type as qlt

qlt.Integer  # INTEGER（引数のない型はクラスのまま使う。qlt.Integer() と同じ）
qlt.Decimal(10, 2)  # DECIMAL(10, 2)（引数のある型は呼び出す）
qlt.List(qlt.Varchar)  # VARCHAR[]
qlt.Struct(a=qlt.Integer, b=qlt.Varchar)  # STRUCT("a" INTEGER, "b" VARCHAR)
```

同じクラスが、式の型も表します。`User.age.cast(qlt.Varchar)` は `Expr[qlt.Varchar]` になり、型チェッカーは以降の式を VARCHAR として扱います（[型安全](typing.md)）。型を値として渡すときも、型注釈に書くときも、同じ名前を使えます。

クラス名は PEP 8 に合わせた CapWords です。DuckDB の型名とは、`TIMESTAMP_MS` が `TimestampMs`、`POINT_2D` が `Point2D` のように書き方が違うものがあります。

## 引数のない型

| クラス | DuckDB の型 |
|---|---|
| `Boolean` | `BOOLEAN` |
| `TinyInt` / `SmallInt` / `Integer` / `BigInt` / `HugeInt` | 符号付き整数 |
| `UTinyInt` / `USmallInt` / `UInteger` / `UBigInt` / `UHugeInt` | 符号なし整数 |
| `Float` / `Double` | 浮動小数点数 |
| `Varchar` | 文字列 |
| `Blob` | バイト列 |
| `Bit` | ビット列 |
| `Uuid` | UUID |
| `Json` | JSON（json 拡張。`Varchar` のサブクラス） |
| `Date` / `Time` / `TimeNs` / `TimeTz` | 日付・時刻 |
| `Timestamp` / `TimestampS` / `TimestampMs` / `TimestampNs` / `TimestampTz` / `TimestampTzNs` | 日時 |
| `Interval` | 期間 |
| `Bignum` / `Variant` | 任意精度の整数 / VARIANT |
| `Geometry` | ジオメトリ（DuckDB 2.0 のコア） |
| `Point2D` / `LineString2D` / `Polygon2D` / `Box2D` / `Box2DF` | spatial 拡張の型 |

spatial 拡張の型を使うと、実行するときに spatial 拡張が自動で読み込まれます。

`Numeric` は「数値のどれか」を表す抽象的なクラスで、型チェックのためだけにあります。DuckDB の型としては使えません。

## 引数を取る型

| 書き方 | DuckDB の型 |
|---|---|
| `qlt.Decimal(10, 2)`（`qlt.Decimal` だけなら `DECIMAL(18, 3)`） | `DECIMAL(10, 2)` |
| `qlt.List(qlt.Varchar)` | `VARCHAR[]` |
| `qlt.Array(qlt.Double, 3)` | `DOUBLE[3]`（固定長） |
| `qlt.Struct(a=qlt.Integer, b="VARCHAR")` | `STRUCT("a" INTEGER, "b" VARCHAR)` |
| `qlt.Map(qlt.Varchar, qlt.Integer)` | `MAP(VARCHAR, INTEGER)` |
| `qlt.Union(n=qlt.Integer, s=qlt.Varchar)` | `UNION("n" INTEGER, "s" VARCHAR)` |
| `qlt.Enum("sad", "ok", "happy")` | `ENUM('sad', 'ok', 'happy')` |
| `qlt.Geometry("OGC:CRS84")`（`qlt.Geometry` だけなら CRS なし） | `GEOMETRY('OGC:CRS84')` |

`List` や `Struct` のように引数が必要な型をクラスのまま渡すと、`TypeError` になります。要素の型には、クラスとインスタンスのどちらも使えます（`qlt.List(qlt.Decimal(10, 2))`）。`Struct` と `Union` のフィールドの型には、型名の文字列も使えます。

## 文字列の型名

型を受け取る場所では、型名の文字列も使えます。ただし文字列の型は型付けされず、式は `Expr[Any]` になります。

```python
User.age.cast("DECIMAL(10, 2)")  # Expr[Any]
User.age.cast(qlt.Decimal(10, 2))  # Expr[Decimal]
# どちらも CAST("users"."age" AS DECIMAL(10, 2))
```

文字列の型名は、英数字・空白・`(精度, スケール)`・`[]` / `[n]` だけで構成されているかを検査します。それ以外（`STRUCT(...)` や、`;` を含む文字列など）は `ValueError` になるので、`qlt.Struct(...)` などのクラスを使ってください。

## CAST

```python
from parrotlet import cast, try_cast

User.age.cast(qlt.Varchar)  # CAST("users"."age" AS VARCHAR)
User.name.try_cast(qlt.Integer)  # TRY_CAST(... AS INTEGER)：失敗すると NULL
cast(1, qlt.BigInt)  # CAST(? AS BIGINT)：Python の値もキャストできる
try_cast("2024-01-01", qlt.Date)
```

## 型なしのカラムに型を付ける

モデルのないテーブルのカラム（`col("x")` や `table("t").c.x`）は型なし（`Expr[Any]`）です。`col()` の `type_=` で型を付けると、そのカラムを型付きの式として扱えます。SQL は変わりません。

```python
created = col("created_at", "events", type_=qlt.Timestamp)  # ColumnRef[Timestamp]
fn.date_trunc("day", created)  # Func[Timestamp]
```

## 型の作成

ユーザー定義の型は `create_type()` で作ります（[DDL](ddl.md)）。

```python
from parrotlet import create_type

create_type("mood", qlt.Enum("sad", "ok", "happy"))
# CREATE TYPE "mood" AS ENUM('sad', 'ok', 'happy')
```

作った型は、`column("mood")` や `cast(x, "mood")` のように型名の文字列で参照します。

## Python の値と DuckDB の型

Python の値をパラメータとして渡すと、DuckDB は次の型として受け取ります。リテラルとして埋め込むとき（`lit()` や DDL）の書き方も示します。

| Python の値 | リテラル |
|---|---|
| `None` | `NULL` |
| `True` / `False` | `true` / `false` |
| `int` | `42` |
| `float` | `1.5`（`nan` / `inf` は `'nan'::DOUBLE` など） |
| `Decimal` | `1.20::DECIMAL` |
| `str` | `'it''s'`（シングルクォートをエスケープ） |
| `pathlib.Path` | `'data/x.csv'`（区切り文字は `/`） |
| `bytes` | `'\x01\xFF'::BLOB` |
| `UUID` | `'...'::UUID` |
| `datetime.datetime` | `'2024-01-02T03:04:05'::TIMESTAMP`（タイムゾーン付きは `TIMESTAMPTZ`） |
| `datetime.date` | `'2024-01-02'::DATE` |
| `datetime.time` | `'03:04:05'::TIME` |
| `datetime.timedelta` | `INTERVAL '86400000000 microseconds'` |
| `list` / `tuple` | `[1, 2, 3]` |
| `dict`（キーは `str`） | `{'a': 1}`（構造体） |
| shapely のジオメトリ | WKB の BLOB を `::GEOMETRY` でキャスト |
