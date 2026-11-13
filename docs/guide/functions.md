# 関数

DuckDB の関数（約 1,200 個）は、モジュールごとに型付きの Python 関数として用意されています。

```python
import parrotlet.functions as fn

# core（json、icu、parquet などの組み込み拡張を含む）
fn.upper(User.name)  # upper("users"."name")
fn.date_trunc("month", Order.ordered_at)  # date_trunc(?, "orders"."ordered_at")
fn.regexp_matches(User.name, "^a", "i")
# spatial 拡張
fn.spatial.st_distance(fn.spatial.st_point(0, 0), Place.geom)
# テーブル関数（FROM で使う）
select().from_(fn.table.read_parquet("data/*.parquet", hive_partitioning=True).as_("p"))
```

| モジュール | 内容 | 戻り値 |
|---|---|---|
| `parrotlet.functions`（`fn`） | スカラー関数・集約関数・ウィンドウ関数・マクロ | `Func[T]` / `AggregateFunc[T]` / `WindowFunc[T]` |
| `parrotlet.functions.spatial`（`fn.spatial`） | spatial 拡張の関数（`ST_*`） | 同上 |
| `parrotlet.functions.table`（`fn.table`） | テーブル関数 | FROM ソース |

各関数の docstring には、DuckDB の説明と使用例、SQL 上の名前が入っています。エディタの補完やホバーで確認できます。一覧は API リファレンス（[core](../reference/functions.md)、[spatial](../reference/spatial.md)、[テーブル関数](../reference/tables.md)）を参照してください。

## 名前の規則

- Python の関数名は、DuckDB の関数名の snake_case です。`ST_AsText` → `st_as_text`、`ST_GeomFromWKB` → `st_geom_from_wkb`、`ST_DWithin` → `st_dwithin` のようになります。生成される SQL は元の名前（`ST_AsText(...)`）のままです。
- DuckDB が小文字で定義している関数（ほとんどの core の関数）は、そのままの名前です（`regexp_matches`、`date_trunc`）。
- Python のキーワードと同じ名前には、末尾に `_` を付けます（`fn.if_`）。
- 別名の関数は同じ関数を指します（`fn.now` は `fn.get_current_timestamp` と同じで、SQL は `get_current_timestamp()` になります）。
- `fn.sum`、`fn.max`、`fn.filter` のように、Python の組み込み関数と同じ名前があります。モジュール経由で呼べば衝突しないので、`from parrotlet.functions import *` は避けてください。
- DuckDB 2.0 でコアに入った `ST_*` 関数（`st_as_text` など）は、`fn` と `fn.spatial` のどちらからも使えます。

## 引数

- 引数には、式と Python の値の両方を渡せます。Python の値はパラメータになります（`fn.upper("abc")` → `upper(?)`）。
- スカラー関数・集約関数・ウィンドウ関数の引数は位置引数です。
- 引数の型が合わないと、型チェッカーがエラーにします（`fn.upper(User.age)`）。
- 関数を取る引数（ラムダ）には、Python のラムダを渡せます（`fn.list_transform(xs, lambda x: x + 1)`）。

## 戻り値の型

関数の型は、DuckDB の関数カタログ（`duckdb_functions()`）から生成しています。引数の型の組み合わせ（オーバーロード）ごとに、戻り値の型が決まります。

```python
fn.length(User.name)  # Func[BigInt]
fn.sum(Order.amount)  # AggregateFunc[Decimal]
fn.sum(User.age)  # AggregateFunc[HugeInt]
fn.avg(User.age)  # AggregateFunc[Double]
fn.date_trunc("day", User.joined)  # Func[Timestamp]
fn.row_number()  # WindowFunc[BigInt]（.over() で式になる）
```

結果の型が引数の型で決まる関数は、手書きのジェネリック関数になっています。

| 関数 | 例 |
|---|---|
| `coalesce`、`ifnull`、`nullif`、`greatest`、`least`、`if_` | `fn.coalesce(User.age, 0)` → `Func[BigInt]` |
| `min`、`max`、`first`、`last`、`any_value`、`arbitrary`、`mode` | `fn.max(Order.ordered_at)` → `AggregateFunc[Timestamp]` |
| `arg_min`、`arg_max`、`min_by`、`max_by` | `fn.arg_max(User.name, User.age)` → `AggregateFunc[Varchar]` |
| `list_value`、`list_pack` | `fn.list_value(1, 2)` → `Func[List[Integer]]` |
| `list_transform`、`list_filter`、`list_reduce`（と別名の `apply`、`filter`、`reduce` など） | ラムダの引数も型推論される |
| `lag`、`lead` | `fn.lag(Order.amount, 1, 0)`（offset と default は省略可） |
| `count` | `fn.count()` は `count(*)`、`fn.count(x)` は NULL 以外の数 |
| `struct_pack` | `fn.struct_pack(a=1, b=User.name)` |

戻り値の型がカタログにない関数（マクロなど）は、`Expr[Any]` を返します。

## スカラー・集約・ウィンドウ

| 種類 | 戻り値 | 追加の引数・メソッド |
|---|---|---|
| スカラー関数 | `Func[T]`（式） | — |
| 集約関数 | `AggregateFunc[T]`（式） | `distinct=`、`order_by=`、`.filter(cond)`、`.over(...)` |
| ウィンドウ関数 | `WindowFunc[T]`（`.over()` を付けると式） | `ignore_nulls=`、`order_by=`、`.over(...)` |

詳しくは[集約とウィンドウ関数](aggregates.md)を参照してください。

## よく使う関数

### 文字列

| 関数 | 例 |
|---|---|
| `upper` / `lower` / `trim` / `length` | `fn.lower(User.name)` |
| `concat` / `concat_ws` | `fn.concat_ws("-", User.country, User.name)` |
| `substring` / `left` / `right` | `fn.left(User.name, 3)` |
| `replace` / `regexp_replace` | `fn.regexp_replace(User.name, "[0-9]", "", "g")` |
| `regexp_matches` / `regexp_extract` | `fn.regexp_extract(User.name, "^(\\w+)", 1)` |
| `split` / `string_split` | `fn.split(User.name, " ")` → `List[Varchar]` |
| `starts_with` / `contains` | `fn.starts_with(User.name, "a")` |

### 日時

| 関数 | 例 |
|---|---|
| `now` / `current_date` | `fn.now()` |
| `date_trunc` | `fn.date_trunc("month", User.joined)` |
| `date_part` / `year` / `month` / `day` | `fn.year(User.joined)` |
| `date_diff` / `date_add` / `age` | `fn.date_diff("day", User.joined, fn.now())` |
| `strftime` / `strptime` | `fn.strftime(User.joined, "%Y-%m-%d")` |
| `make_date` / `make_timestamp` | `fn.make_date(2026, 1, 1)` |
| `to_timestamp` / `epoch` | `fn.to_timestamp(1_700_000_000)` |

### リスト

| 関数 | 例 |
|---|---|
| `list_value` / `list_pack` | `fn.list_value(1, 2, 3)` |
| `len` / `array_length` | `fn.len(User.tags)` |
| `list_contains` / `list_has_any` / `list_has_all` | `fn.list_contains(User.tags, "admin")` |
| `list_distinct` / `list_sort` / `list_reverse` | `fn.list_sort(User.tags)` |
| `list_transform` / `list_filter` / `list_reduce` | ラムダを渡す |
| `list_aggregate` | `fn.list_aggregate(xs, "sum")` |
| `unnest`（SELECT リストで行に展開） | `select(func.unnest(User.tags))`（型付きの関数はないので `func` を使う。FROM では `fn.table.unnest`） |

### 条件・NULL

| 関数 | 例 |
|---|---|
| `coalesce` / `ifnull` | `fn.coalesce(User.country, "unknown")` |
| `nullif` | `fn.nullif(User.name, "")` |
| `if_` | `fn.if_(User.age >= 20, "adult", "minor")` |
| `greatest` / `least` | `fn.greatest(Order.amount, 0)` |

### その他

| 関数 | 例 |
|---|---|
| `nextval` / `currval` | `fn.nextval("seq")` |
| `getvariable` | `fn.getvariable("cutoff")`（`set_variable()` で設定した値） |
| `hash` | `fn.hash(User.name)` |
| `uuid` / `gen_random_uuid` | `fn.uuid()` |
| `random` / `setseed` | `fn.random()` |
| `typeof` | `fn.typeof(User.age)` |

## テーブル関数

`parrotlet.functions.table`（`fn.table`）の関数は、FROM で使うソースを返します。先頭の引数は位置引数、残りはキーワード引数（SQL では `name := value`）です。

```python
fn.table.read_csv("x.csv", header=True, delim="|")
fn.table.range(1, 10).as_("r")  # r.c.range
fn.table.generate_series(1, 10, 2)
fn.table.unnest([1, 2, 3]).as_("u", ["x"]).with_ordinality()
```

詳しくは[テーブルと FROM ソース](sources.md#table-functions)と[ファイルの読み書き](files.md)を参照してください。

## 型なしの呼び出し

`parrotlet.func` は、任意の関数（自作のマクロ、拡張機能の関数など）を型なしで呼び出します。

```python
from parrotlet import func

func.my_macro(User.id)  # my_macro("users"."id")
func("weird name", 1)  # "weird name"(?)
func.if_(TRUE, 1, 2)  # if(true, ?, ?)：末尾の _ は取り除かれる
func.count()  # count(*)
func.string_agg(User.name, ",", order_by=User.name, distinct=True)
```

- 戻り値は `AggregateFunc[Any]` なので、スカラー関数としても集約関数としても使えます（`.filter()`、`.over()` も使えます）。
- 引数の型は検査されません。結果を型付きにしたいときは `.cast(...)` を付けます。
- 名前が識別子として正しければクォートせず（大文字小文字を区別しない検索のため）、そうでなければクォートします。

## 再生成

DuckDB を更新したら、関数モジュールを再生成してください（spatial 拡張がインストールされます）。

```bash
uv run python scripts/generate_functions.py
```

生成の仕組みは[関数の生成](../internals/functions.md)を参照してください。
