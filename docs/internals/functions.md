# 関数の生成

`parrotlet.functions`（`fn`）、`parrotlet.functions.spatial`、`parrotlet.functions.table` の約 1,200 個の関数は、手で書いたものではありません。`scripts/generate_functions.py` が DuckDB の関数カタログ（`duckdb_functions()`）を読んで生成しています。

```bash
uv run python scripts/generate_functions.py
```

DuckDB を更新したら、このスクリプトを再実行します。生成したファイルの先頭には、元にした DuckDB のバージョンが書かれます。

## 生成されるもの

| ファイル | 内容 |
|---|---|
| `functions/_core.py` | core と組み込み拡張機能（json、icu、parquet など）のスカラー・集約・ウィンドウ関数とマクロ |
| `functions/table.py` | core のテーブル関数（`read_parquet`、`range` など） |
| `functions/spatial.py` | spatial 拡張の関数。拡張機能のいらない core の `ST_*` 関数も再エクスポートする |

`functions/__init__.py` は、`_core` と、手書きの `_generic` をまとめてエクスポートします。

## 処理の流れ

1. **カタログを読む**：spatial を読み込んだ接続で `duckdb_functions()` を問い合わせ、関数名、種類、拡張機能、別名、説明、例、引数名、引数の型、戻り値の型、可変長引数を取得する
2. **関数ごとにまとめる**：同じ名前の行（オーバーロード）を1つの `Function` にまとめる
    - 同じ名前でスカラーと集約の両方があれば、集約として扱う（`AggregateFunc` はスカラーとしても使える）
    - テーブル関数と名前が衝突したら、テーブル関数の名前に `_table` を付ける
    - `_generic.py` に手書きした関数は読み飛ばす
3. **型を変換する**：カタログの型文字列を構文木（`T`）に変換し、幽霊型の注釈にする
4. **オーバーロードを並べる**：狭い型を先に並べる
5. **書き出す**：オーバーロード付きの関数定義を頭文字ごとに `# region` / `# endregion` で囲んで書き出し、`ruff format` で整形する

## 型の変換

カタログの型文字列は、次のように変換します。

| カタログの型 | 引数の注釈 | 戻り値 |
|---|---|---|
| `VARCHAR` | <code>_E[_t.Varchar] &#124; str</code> | `_t.Varchar` |
| `INTEGER` | <code>_E[_t.Integer] &#124; int</code> | `_t.Integer` |
| `TIMESTAMP` | <code>_E[_t.Timestamp] &#124; _dt.date</code> | `_t.Timestamp` |
| `GEOMETRY` | <code>_E[_t.Geometry] &#124; _Geom</code> | `_t.Geometry` |
| `T`、`K`、`V` | <code>_E[T] &#124; _PyScalar</code>（型変数） | 引数に出てくれば `T`、なければ `Any` |
| `T[]` / `T[n]` | <code>_E[_t.List[T]] &#124; _PyList</code> | `_t.List[T]` / `_t.Array[T]` |
| `MAP(K, V)` | <code>_E[_t.Map[K, V]] &#124; _PyDict</code> | `_t.Map[K, V]` |
| `LAMBDA` | Python の呼び出し可能オブジェクト、または `Lambda` | — |
| `ANY`、不明な型 | `_Value`（任意の式や値） | `Any` |

引数の注釈には、式に加えて、その SQL 型に対応する Python の値（`LITERAL` テーブル）も並べます。`fn.upper("abc")` のように値を直接渡せるのはこのためです。

固定長配列（`T[n]`）の引数には、リストも渡せるようにしています。DuckDB はリストを固定長配列に暗黙に変換するためです。

マクロ（`macro`、`table_macro`）はカタログに戻り値の型がないので、戻り値は `Any` になります。

## オーバーロードの順番

型チェッカーは、オーバーロードを上から順に試し、最初に一致したものを使います。共変な `Expr[T]` では、`Expr[Integer]` は `Expr[Double]` の引数にも一致するので、広い型が先にあると、狭い型のオーバーロードが選ばれません。

そこで、引数の型を「狭い順」に並べ替えます。幽霊型のクラスの MRO が長いほど（継承が深いほど）狭い型とみなし、リストやマップ、型変数、`Any` をその後に並べます。

```python
@overload
def sum(arg: _E[_t.SmallInt], /, ...) -> _A[_t.HugeInt]: ...
@overload
def sum(arg: _E[_t.Integer] | int, /, ...) -> _A[_t.HugeInt]: ...
...
@overload
def sum(
    arg: _E[_t.Decimal] | int | float | _PyDecimal, /, ...
) -> _A[_t.Decimal]: ...
...
@overload
def sum(arg: _E[_t.Double] | int | float | _PyDecimal, /, ...) -> _A[_t.Double]: ...
```

正確には、オーバーロードを「引数の数、可変長引数の有無、各引数の狭さ」の順で並べ替えます。シグネチャが同じになったオーバーロードは1つにまとめます。

オーバーロードが 48 個（`MAX_OVERLOADS`）を超える関数は、組み合わせが多すぎて役に立たないので、型付けをあきらめて `*args: Any` の1つのシグネチャだけを出力します。

## 生成される関数の形

関数の種類ごとに、戻り値の型と実装が変わります。実装はどれも `_runtime.py` のヘルパーを呼ぶだけです。

| 種類 | 戻り値 | 実装 | 追加の引数 |
|---|---|---|---|
| スカラー | `Func[T]` | `_rt.scalar(name, args, extension)` | — |
| 集約 | `AggregateFunc[T]` | `_rt.aggregate(...)` | `distinct`、`order_by` |
| ウィンドウ | `WindowFunc[T]` | `_rt.window(...)` | `ignore_nulls`、`order_by` |
| テーブル | `FunctionSource` | `_rt.table(name, args, options, extension)` | 名前付きオプション（キーワード引数） |

```python
def upper(string: _E[_t.Varchar] | str, /) -> _F[_t.Varchar]:
    """Converts `string` to upper case.

    Example: `upper('Hello')`

    SQL: `upper`"""
    return _rt.scalar("upper", (string,))
```

- 関数名は Python の識別子にする：大文字を含む名前はスネークケースに変換し（`ST_GeomFromText` → `st_geom_from_text`）、予約語なら末尾に `_` を付ける。小文字で登録されている core の `ST_*` 関数は単語の区切りが分からないので、`SNAKE_OVERRIDES` で個別に指定する（`st_astext` → `st_as_text`）
- スカラー・集約・ウィンドウ関数の引数は位置専用（`/`）。引数名はカタログから取り、予約語や重複には `_` や番号を付ける
- テーブル関数は、最初の引数だけを位置引数にし、残りをキーワード専用のオプション（既定値 `None`）にする。引数の数が違うオーバーロードがある関数（`range(stop)` / `range(start, stop)` など）は、すべて位置引数にする
- spatial の関数は `extension="spatial"` を渡すので、使うと拡張機能が自動で読み込まれる
- docstring には、カタログの説明と例と SQL 上の名前を入れる
- カタログで別名とされている関数（`now` → `get_current_timestamp` など）は、`now = get_current_timestamp` のような代入で出力する

### ランタイムのヘルパー

`_runtime.arg()` は、関数の引数を次のように変換します。

- Python の呼び出し可能オブジェクト（`lambda x: x * 2`）は `make_lambda()` で SQL のラムダにする。Python の引数名を SQL のラムダ引数にし、それぞれを `ColumnRef` として関数を1回呼んで、本体の式を作る
- それ以外は `to_expr()` で式にする（Python の値はパラメータになる）

```python
>>> select(fn.list_transform(fn.list_value(1, 2), lambda x: x * 2)).sql
'SELECT list_transform(list_value(?, ?), lambda "x": ("x" * ?))'
```

テーブル関数の名前付きオプションは、`None` でないものだけが `name := value` として出力されます。

## 手書きの関数

カタログの型だけでは表せない関数は `functions/_generic.py` に手書きし、生成の対象から外しています（スクリプトの `HANDWRITTEN`）。主に次の2種類です。

- 戻り値の型が引数の型で決まる関数：`coalesce`、`ifnull`、`nullif`、`greatest`、`least`、`max`、`min`、`first`、`last`、`any_value`、`arg_max`、`mode`、`lag`、`lead` など
- ラムダを取る高階関数：`list_transform`、`list_filter`、`list_reduce` とその別名

`count()` も手書きで、引数を省略すると `count(*)` になります。

## 型付けされていない逃げ道

生成された関数にない関数（ユーザー定義のマクロなど）は、`parrotlet.func` で呼べます。

```python
func.my_macro(User.age)  # my_macro("users"."age")
func("weird name", 1)  # "weird name"(?)
```

`func.<name>` は `__getattr__` で任意の名前を受け付け、`AggregateFunc[Any]` を返します。型の検査はされませんが、`distinct` や `order_by`、`.filter()`、`.over()` は使えます。名前の末尾の `_` は取り除かれるので、Python の予約語と同じ名前の関数も `func.if_(...)` のように呼べます。
