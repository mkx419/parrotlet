# 関数

DuckDB の関数は、名前空間（モジュール）ごとに型付きの Python 関数として用意しています。

```python
from parrotlet import functions as F  # core（json, icu, parquet などの組み込み拡張を含む）
from parrotlet.functions import spatial as ST  # spatial 拡張
from parrotlet.functions import tables as TF  # テーブル関数（FROM 用）

F.upper(User.name)
F.date_trunc("month", Order.ordered_at)
F.regexp_matches(User.name, "^a", "i")
ST.st_distance(ST.st_point(0, 0), Place.location)
ST.st_as_text(Place.location)
select().from_(TF.read_parquet("data/*.parquet", hive_partitioning=True).as_("p"))
```

## 名前の規則

- Python の関数名は、DuckDB の関数名の snake_case です。`ST_AsText` → `st_as_text`、`ST_GeomFromWKB` → `st_geom_from_wkb`、`ST_DWithin` → `st_dwithin` のようになります。生成される SQL は元の名前（`ST_AsText(...)`）のままです。
- DuckDB が小文字で定義している関数（大半の core 関数）は、そのままの名前です（`regexp_matches`、`date_trunc`）。
- Python のキーワードと重なる名前は、末尾に `_` を付けます（`F.if_`）。
- `F.sum` / `F.max` / `F.filter` のように、Python の組み込み関数と同じ名前もあります。モジュール経由で呼べば衝突しないので、`from parrotlet.functions import *` は避けてください。
- DuckDB 2.0 でコアに入った `ST_*` 関数（`st_as_text` など）は、`spatial` モジュールからも使えます。

## 型

関数の型は、DuckDB の関数カタログ（`duckdb_functions()`）から生成しています。オーバーロードごとに引数の型と戻り値の型が付いています。

```python
F.length(User.name)  # Func[BigInt]
F.sum(Order.amount)  # AggregateFunc[Decimal]
F.row_number()  # WindowFunc[BigInt]（.over() で式になる）
F.upper(User.age)  # 型エラー
```

結果の型が引数の型で決まる関数は、手書きのジェネリック関数になっています。

| 関数 | 例 |
|---|---|
| `coalesce`、`ifnull`、`nullif`、`greatest`、`least`、`if_` | `F.coalesce(User.age, 0)` → `Func[BigInt]` |
| `min`、`max`、`first`、`last`、`any_value`、`mode`、`arg_min`、`arg_max` | `F.max(Order.ordered_at)` → `AggregateFunc[Timestamp]` |
| `list_value`、`list_transform`、`list_filter`、`list_reduce` | ラムダの引数も型推論される |
| `lag`、`lead` | 省略可能な offset / default 付き |
| `count` | `F.count()` は `count(*)` |
| `struct_pack` | `F.struct_pack(a=1, b=User.name)` |

## 集約・ウィンドウの引数

- 集約関数：`distinct=`、`order_by=`（順序付き集約）を指定でき、`.filter(cond)` と `.over(...)` が使えます。
- ウィンドウ関数：`ignore_nulls=` と `order_by=`（引数内の ORDER BY）を指定でき、`.over(...)` を付けると式になります。

## テーブル関数

`parrotlet.functions.tables` の関数は、FROM で使うソースを返します。先頭の引数は位置引数、残りはキーワード引数（SQL では `name := value`）です。

```python
TF.read_csv("x.csv", header=True, delim="|")
TF.range(1, 10).as_("r")  # r.c.range
TF.unnest([1, 2, 3]).as_("u", ["x"]).with_ordinality()
```

## 型なしの呼び出し

`parrotlet.func.<name>(...)` は、任意の関数（自作のマクロなど）を型なしで呼び出します。

```python
from parrotlet import func

func.my_macro(User.id)
func("weird name", 1)
```

## 再生成

DuckDB を更新したら、関数モジュールを再生成してください（spatial 拡張をインストールします）。

```bash
uv run python scripts/generate_functions.py
```
