# 内部設計

このセクションでは、parrotlet がどう作られていて、Python のコードがどのように SQL になり、DuckDB で実行されるのかを説明します。使い方は[ガイド](../guide/getting-started.md)を参照してください。

## 設計の柱

parrotlet は、次の4つの考え方で作られています。

不変な構文木
:   式もステートメントも、frozen な dataclass の木です。`.where(...)` などのメソッドは自分を書き換えず、変更を加えた新しいオブジェクトを返します。途中まで組み立てたクエリを安全に使い回せます。

遅延コンパイル
:   木を組み立てている間は SQL 文字列を作りません。`.sql` や `.execute()` が呼ばれた時点で、木を再帰的にたどって `Query`（SQL 文字列・パラメータ・必要な拡張機能）を作ります。

型は静的検査のためだけに使う
:   `Expr[T]` の `T` は「幽霊型（phantom type）」です。実行時には何もしませんが、pyright などの型チェッカーが、演算子や関数に渡す引数の型の組み合わせを検査します。

値は常にパラメータ
:   Python の値は `?` パラメータとして DuckDB に渡します。DuckDB がパラメータを受け付けない場所でだけ、エスケープ済みのリテラルとして展開します。

## モジュール構成

`src/parrotlet/` の構成は次のとおりです。

| モジュール | 内容 |
|---|---|
| `query.py` | `Query`・`Node`（すべての基底）・識別子のクォート・リテラル・パラメータ |
| `type.py` | DuckDB の型のクラス（`Integer`、`Decimal`、`List[T]` ...）。値としては CAST やカラム定義の型、型パラメータとしては式の型。継承で暗黙の型変換を表す |
| `expr.py` | `Expr[T]` と各種式ノード（演算子、関数呼び出し、CASE、ウィンドウ、ラムダ ...） |
| `source.py` | FROM に置けるもの（`Table`、サブクエリ、CTE、テーブル関数、VALUES、ファイル） |
| `model.py` | `Model`・`Column`：テーブル定義と行型を兼ねるクラス |
| `statement/` | SELECT / INSERT / UPDATE / DELETE / MERGE / PIVOT / COPY / DDL / ユーティリティ |
| `execution.py` | DuckDB での実行：拡張機能の導入、パラメータを使えない文の再試行 |
| `database.py` | `Database`：接続を持ち、ステートメントをバインドする |
| `appender.py` | DuckDB のネイティブ appender の型付きラッパー |
| `result.py` | 結果の行を dataclass などに変換する |
| `functions/` | DuckDB の関数カタログから生成した型付き関数 |
| `functions/_core.py` | （生成）core の関数 |
| `functions/spatial.py` | （生成）spatial 拡張の関数 |
| `functions/table.py` | （生成）テーブル関数 |
| `functions/_generic.py` | （手書き）引数の型で戻り値の型が決まる関数 |
| `functions/_runtime.py` | 生成コードが呼ぶ共通のヘルパー |

依存の向きは、おおむね上から下です。`query.py` はどこにも依存せず、`expr.py` は `query.py` と型の定義だけに依存します。`expr.py` は、自分に依存する `source.py` のテーブルを、`Qualified` プロトコル（`qualifier()` を持つもの）としてだけ扱います。`statement/` や `database.py` は、それより下の層をすべて使います。

## クエリが実行されるまで

```python
db.select(User.name).from_(User).where(User.age >= 20).fetchall()
```

この1行は、次の順で処理されます。

```text
User.age
  │  Column.__get__（クラスからの参照）
  ▼
ColumnRef[BigInt]
  │  Expr.__ge__(20)
  ▼
BinaryOp(ColumnRef, ">=", Param(20))
  │  .select() / .from_() / .where() が新しい Select を返す
  ▼
Select(...)
  │  Node.build() を再帰的に呼ぶ
  ▼
Query(sql, params, extensions)
  │  必要な拡張機能を読み込む（INSTALL / LOAD）
  ▼
con.execute(sql, params)
  │  fetchall() / fetch_as(User)
  ▼
タプル / Model / dataclass
```

1. **式を作る**：`User.age` はクラスからの属性参照なので、`Column` デスクリプタが `ColumnRef("age", ("users",))` を返します。`>= 20` は `Expr.__ge__` が受け取り、`20` を `Param(20)` にして `BinaryOp` を返します。この時点では SQL は作られません（[モデル](model.md)、[型安全の仕組み](typing.md)）。
2. **ステートメントを作る**：`db.select(...)` は `Select` dataclass を作り、`_db` フィールドに `Database` を記録します。`.from_()` や `.where()` は `dataclasses.replace` で新しい `Select` を返します（[SQL の組み立て](compilation.md)）。
3. **コンパイルする**：`.fetchall()` の中で `build()` が呼ばれます。各ノードが自分の SQL 断片を `Query` として返し、それを `+` で連結します。パラメータと必要な拡張機能も、SQL と同じ順で一緒に連結されます。
4. **実行する**：`_db` があればその接続で、なければ DuckDB のデフォルト接続で実行します。必要な拡張機能を先に読み込み、パラメータを受け付けない文はリテラルを展開して再試行します（[実行と結果](execution.md)）。

```python
>>> q = (
...     select(User.name, fn.upper(User.name))
...     .from_(User)
...     .where(User.age >= 20, User.name.like("a%"))
... )
>>> print(q.sql)
SELECT "users"."name", upper("users"."name") FROM "users"
  WHERE (("users"."age" >= ?) AND ("users"."name" LIKE ?))
>>> q.params
(20, 'a%')
>>> print(q.sql_inline)
SELECT "users"."name", upper("users"."name") FROM "users"
  WHERE (("users"."age" >= 20) AND ("users"."name" LIKE 'a%'))
```

## このセクションの構成

| ページ | 内容 |
|---|---|
| [SQL の組み立て](compilation.md) | `Node` と `Query`、パラメータとリテラル、識別子のクォート、コンテキスト変数による出力の切り替え |
| [型安全の仕組み](typing.md) | 幽霊型、継承による暗黙の型変換、制約付き TypeVar、`self` の型で絞るオーバーロード |
| [モデル](model.md) | `Model.__init_subclass__`、`Column` デスクリプタ、型の推論、CREATE TABLE の生成 |
| [実行と結果](execution.md) | `Database` とバインド、拡張機能の自動導入、再試行、結果の変換、appender |
| [関数の生成](functions.md) | `scripts/generate_functions.py` が DuckDB のカタログから型付き関数を作る仕組み |
