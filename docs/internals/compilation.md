# SQL の組み立て

parrotlet のすべての部品（式、FROM ソース、ステートメント、データ型、制約）は `Node` のサブクラスです。`Node` は `build()` で `Query` を返す、という1つの約束だけを持ちます。SQL は、この `build()` を木の根から再帰的に呼ぶことで組み立てられます。

## Query：コンパイル結果 {#query}

`Query`（`query.py`）は、コンパイル済みの SQL 断片を表す frozen な dataclass です。

```python
@dataclass(frozen=True, slots=True)
class Query:
    sql: str  # SQL 文字列（パラメータの位置は ?）
    params: tuple[object, ...] = ()  # ? に対応する値（出現順）
    extensions: frozenset[str] = frozenset()  # 実行前に読み込む DuckDB 拡張機能
```

`Query` どうしは `+` で連結できます。SQL は文字列として、パラメータはタプルとして、拡張機能は集合の和として、それぞれ連結されます。

```python
Query("a = ?", (1,)) + Query(" AND b = ?", (2,))
# Query(sql='a = ? AND b = ?', params=(1, 2))
```

SQL とパラメータを常にペアで連結するので、`?` とパラメータの順番がずれることはありません。拡張機能も同じように伝搬するので、spatial の関数を木のどこかで使えば、最終的な `Query.extensions` に `"spatial"` が入ります。

```python
>>> wkt = "POLYGON((0 0,0 1,1 1,1 0,0 0))"
>>> select(fn.spatial.st_area(fn.spatial.st_geom_from_text(wkt))).build()
Query(sql='SELECT ST_Area(ST_GeomFromText(?))',
      params=('POLYGON((0 0,0 1,1 1,1 0,0 0))',),
      extensions=frozenset({'spatial'}))
```

## Node：すべての部品の基底

`Node` は抽象メソッド `build()` を持ち、それ以外の便利なメソッドはすべて `build()` の上に作られています。

| メンバー | 働き |
|---|---|
| `build()` | `Query` を返す（サブクラスが実装する） |
| `sql` / `params` | `build()` の結果の SQL とパラメータ |
| `build_inline()` / `sql_inline` | パラメータをリテラルとして展開してビルドする（ログやデバッグ用） |
| `execute()` / `execute_on()` | 実行して DuckDB のカーソルを返す（[実行と結果](execution.md)） |
| `fetchall()` / `fetchone()` / `df()` / `pl()` / `fetch_as()` / `fetch_one_as()` | 実行して結果を返す |

式（`Expr`）もステートメント（`Select` など）も `Node` なので、`fn.upper(User.name).sql` のように式だけをコンパイルしたり、式を単体で実行したりもできます。

### 組み立てのヘルパー

各ノードの `build()` は、`query.py` と `statement/base.py` の小さなヘルパーで書かれています。

| ヘルパー | 働き |
|---|---|
| `concat(*parts)` | 断片を連結する。`None` は読み飛ばすので、省略可能な句を `x if cond else None` で書ける。`str` は信頼済みの SQL として扱う |
| `join(sep, parts)` | 区切り文字で連結する（カラムリストなど） |
| `text(sql)` | 信頼済みの SQL 断片。引数は `LiteralString` 型なので、ユーザー入力の文字列を渡すと型チェッカーが警告する |
| `param(value)` | 値をパラメータ（または後述のインラインリテラル）にする |
| `ident_list(names)` | 識別子をクォートして括弧で囲んだリストにする（`("a", "b")`） |
| `clause(keyword, node)` / `list_clause(keyword, items)` | `" WHERE <式>"` や `" FROM a, b"` のような句を作る。`node` が `None`、`items` が空なら `None` を返す |

たとえば `BinaryOp` の `build()` は次の1行です。

```python
def build(self) -> Query:
    return concat("(", self.left, Query(f" {self.op} "), self.right, ")")
```

二項演算は常に括弧で囲みます。演算子の優先順位を考えずに済み、`(a + b) * c` のような木の構造がそのまま SQL に出ます。

`Select.build()` も同じ考え方で、句ごとの断片（未指定なら `None`）を `concat` に並べるだけです。

```python
return concat(
    with_clause(self._ctes, recursive=self._recursive),
    "SELECT ",
    distinct,
    join(", ", self._columns) if self._columns else Query("*"),
    list_clause("FROM", self._from),
    *self._joins,
    clause("WHERE", self._where),
    ...,
)
```

## 不変なビルダー

ステートメントは `@dataclass(frozen=True, slots=True, eq=False)` です。ビルダーメソッドは `dataclasses.replace` で新しいインスタンスを返します。

```python
def where(self, *conditions: Bool) -> Select:
    return replace(self, _where=and_where(self._where, conditions))
```

```python
base = db.from_(User).where(User.age >= 20)
adults_named_a = base.where(User.name.like("a%"))  # base は変わらない
adults_by_age = base.order_by(User.age)
```

複数のステートメントに共通するフィールドとメソッドは、dataclass の基底クラスにまとめています。

| 基底クラス | フィールド | メソッド | 継承するもの |
|---|---|---|---|
| `BoundStatement` | `_db` | `_database()` | すべてのステートメント |
| `QueryStatement` | `_ctes`、`_order_by`、`_limit` など | `with_()`、`order_by()`、`limit()`、`union()` など | SELECT・集合演算・PIVOT |
| `DmlStatement` | `_ctes`、`_returning` | `with_()`、`returning()` | INSERT・UPDATE・DELETE・MERGE |
| `Filterable`（フィールドなし） | — | `where()` | SELECT・UPDATE・DELETE |

基底クラスのフィールドは `kw_only=True` なので、サブクラスは自分のフィールドを位置引数のまま先頭に置けます（`Insert(table, columns)`）。slots を使う dataclass は、フィールドを持つ基底クラスを2つ同時には継承できないため、`Filterable` だけはフィールドを持たない mixin にして、`_where` は各サブクラスが宣言します。コピーはどれも `Statement._replace()`（`dataclasses.replace` の薄いラッパー）で作ります。

フィールド名が `_` で始まるのは、ビルダーメソッド（`where()` など）と名前が衝突しないようにするためです。

`eq=False` にしているのは、式の `==` を SQL の比較（`BinaryOp`）として使うためです。dataclass が生成する `__eq__` で上書きされないようにしています。同じ理由で、`Expr` は `__hash__ = object.__hash__` を明示しています。また、`if User.age > 3:` のような誤用を防ぐため、`Expr.__bool__` は `TypeError` を送出します。

## 値の扱い：パラメータとリテラル

Python の値は、式の中に入るときに `to_expr()` で `Param` に包まれます。

```python
def to_expr(value: object) -> Expr[Any]:
    if isinstance(value, Expr):
        return value  # 式はそのまま
    if isinstance(value, Node):
        return Subquery(value)  # ステートメントはサブクエリ
    return Param(value)  # それ以外の値はパラメータ
```

`Param.build()` は `param(value)` を呼び、通常は `Query("?", (value,))` を返します。ただし、次の場合はリテラルとして展開します。

| 場面 | 出力 | 理由 |
|---|---|---|
| 通常 | `?` | SQL インジェクションを防ぐ。DuckDB にプリペアドステートメントとして渡す |
| shapely のジオメトリ | `CAST(? AS GEOMETRY)` | WKB のバイト列として送り、DuckDB 側で GEOMETRY に変換する |
| リストや構造体の中のジオメトリ | リテラル | DuckDB は入れ子のジオメトリをパラメータとして受け取れない |
| `inline_params()` の中 | リテラル | DDL など、`?` を受け付けない場所（後述） |

リテラルへの変換は `render_literal()` が担当します。文字列はシングルクォートをエスケープし、日時は `'2024-01-01T00:00:00'::TIMESTAMP` のように型付きで出力します。`NaN` や `inf` は `'nan'::DOUBLE` に、`bytes` は `'\xAB...'::BLOB` に、`list` は `[...]` に、`dict` は `{'k': v}`（構造体）になります。変換できない型は `TypeError` になります。

### 定数でなければならない場所

DuckDB の文法上、バインド時に定数でなければならない場所があります。そこでは `?` を使わず、常にリテラルで出力します。

- 構造体のキーとリストの整数インデックス（`Index` ノード）
- `* LIKE 'pattern'` などのスターのパターン
- `FROM 'data/*.parquet'` のファイルパス
- `LIKE ... ESCAPE` のエスケープ文字
- COPY / ATTACH などのオプション値（`render_options()`）

## コンテキスト変数による出力の切り替え {#context-vars}

同じ式でも、置かれる場所によって出力を変える必要があります。parrotlet は、これを `contextvars.ContextVar` で実現しています。出力の仕方をノードの引数で受け渡す代わりに、`with` ブロックの間だけ出力の仕方を切り替えます。

### `inline_params()`：パラメータをリテラルに

```python
with inline_params():
    query = node.build()  # この中の param() はすべてリテラルを返す
```

次の場所で使われています。

- `CREATE TABLE` のカラム定義（`DEFAULT`、`CHECK`、`GENERATED`）
- `CREATE VIEW`、`CREATE MACRO`、`ALTER TABLE`、`CREATE INDEX` などの DDL（`SimpleStatement(..., inline=True)`）
- `SET VARIABLE`、COPY などのオプション
- `Node.build_inline()` / `sql_inline`（デバッグ用）
- 実行時の再試行（[実行と結果](execution.md#inline-retry)）

`CREATE TABLE ... AS SELECT` は例外で、DuckDB が SELECT 部分ではパラメータを受け付けるので、パラメータのまま出力します。

### `unqualified_columns()`：テーブル名を付けない

`User.age` は通常 `"users"."age"` と出力されます。しかし、CREATE TABLE の `CHECK` や `GENERATED` の式、PIVOT の中では、テーブル名で修飾したカラム名を書けません。`unqualified_columns()` の中では、`ColumnRef` はカラム名だけ（`"age"`）を出力します。

```python
>>> print(create_table(User).sql)
CREATE TABLE "users" ("id" BIGINT PRIMARY KEY, "name" VARCHAR NOT NULL,
  "age" BIGINT CHECK (("age" >= 0)),
  "joined" TIMESTAMP NOT NULL DEFAULT get_current_timestamp())
```

`ContextVar` を使っているので、スレッドや asyncio のタスクをまたいでも、切り替えが他のビルドに影響することはありません。

## 識別子

識別子は `quote_ident()` で常にダブルクォートで囲み、中の `"` は `""` にエスケープします。予約語や大文字小文字を含む名前でも、そのまま正しく扱えます。`qualified("main", "users")` は `"main"."users"` になります。

関数名だけは例外で、`[A-Za-z_][A-Za-z0-9_]*` に一致すればクォートしません（`function_name()`）。DuckDB の関数名の検索は大文字小文字を区別しないので、クォートすると `ST_Area` などが見つからなくなるためです。

型（`parrotlet.type` のクラス）は文字列で受け取ることもできます。その場合は `to_type()` が `INTEGER`、`DECIMAL(10, 2)`、`VARCHAR[]` のような形だけを許可する正規表現で検査し、それ以外は `ValueError` にします。

## t-string による生の SQL

Python 3.14 のテンプレート文字列（t-string）で、生の SQL を安全に書けます。

```python
db.sql(t"SELECT * FROM users WHERE id = {user_id}")
fn.upper(sql(t"name || {suffix}"))
```

`RawSQL` ノードはテンプレートの各部分を順にたどり、文字列の部分はそのまま、補間された値は次のように扱います。

- `Query` や `Node` なら、それをビルドして埋め込む（式やサブクエリを混ぜられる）
- それ以外の値は `param()` でパラメータにする

f-string と違って、補間した値が SQL 文字列に直接連結されることはありません。
