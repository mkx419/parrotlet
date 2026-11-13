# 実行と結果

このページでは、コンパイルした `Query` がどの接続で、どのように実行されるか、そして結果がどう Python のオブジェクトになるかを説明します。

## どの接続で実行するか

`Node.execute(con=None)` は、次の順で実行先を決めます。

1. 引数 `con` が渡されれば、その接続
2. ノードがバインドされている `Database`（`_database()` が返すもの）
3. どちらもなければ、`duckdb.default_connection()`

```python
def execute(self, con=None):
    db = self._database()
    if con is None and db is not None:
        return db.execute(self)
    return self.execute_on(con)
```

`Node._database()` は `None` を返し、ステートメントの基底クラス `BoundStatement` がこれをオーバーライドして `_db` フィールドを返します。`Node` は一番下の層なので、`Database` やステートメントのフィールドを直接は参照しません。RETURNING の有無も同じで、`fetch_as()` は `Node._returns_rows()` に問い合わせ、`DmlStatement` が `_returning` を見て答えます。

実際に DuckDB に問い合わせる処理は、すべて `execution.py` にあります。`Query.execute()` は `run_query()` を、`Node.execute_on()` は `run_node()` を呼ぶだけなので、どの入口から実行しても同じ手順になります。

## Database とバインド

`Database` は DuckDB の接続（`self.connection`）を1つ持ちます。`db.select(...)`、`db.insert(...)` などは、普通の `select()`、`insert()` で作ったステートメントを `db.bind()` でバインドしたものです。

```python
def bind(self, statement):
    return statement._replace(_db=self)


def select(self, *columns):
    return self.bind(select(*columns))
```

ステートメントの dataclass は `_db` フィールドを持っていて、ビルダーメソッドは `replace` で新しいインスタンスを作るので、`_db` は `.where()` などを何度呼んでも引き継がれます。`_db` は SQL の生成には関わらず、実行先を決めるためだけに使われます。

`select().union(...)` で作る `Compound` は、左右どちらかの `_db` を引き継ぎます。

`db.register` はクラスデコレーターで、`create_table(model).if_not_exists()` をその場で実行してからクラスをそのまま返します。

`db.execute()` は、`Node`、`Query`、t-string（`Template`）のどれでも受け付けます。t-string は `RawSQL` でラップしてから実行します。

## 拡張機能の自動導入

`Query.extensions` には、木の中で使われた拡張機能の名前が集まっています（[SQL の組み立て](compilation.md#query)）。拡張機能を必要とするのは、次のノードです。

- spatial の関数（`Func(..., extension="spatial")`）
- spatial の型（`qlt.Point2D` など、`sql_extension = "spatial"` を持つクラス）

`run_query()`（`Query.execute()` の中身）は、実行の前に `ensure_extensions()` を呼びます。`duckdb_extensions()` を見て、読み込み済みなら何もせず、未インストールなら `INSTALL`、未ロードなら `LOAD` します。拡張機能の名前は `\w+` で検査してから SQL に埋め込みます。

さらに、事前に分からなかった拡張機能にも対応します。DuckDB のエラーメッセージが `... exists in the X extension` に一致したら、`X` を導入して1回だけ再実行します。生成された関数に拡張機能の情報がなくても、DuckDB が教えてくれる拡張機能は自動で読み込まれます。

`Database(auto_install=False)` にすると、どちらの仕組みも無効になります。`Database(extensions=[...])` で、接続時に読み込んでおくこともできます。

## パラメータを受け付けない文の再試行 {#inline-retry}

DuckDB には、パラメータを使えない文があります。たとえば、IN リストのない PIVOT は DuckDB の中で複数の文に展開されるので、`?` を含められません。マクロの中のパラメータも使えません。

`run_node()`（`Node.execute_on()` の中身）は、まずパラメータ付きで実行し、次のどれかを含むエラーになったら、`build_inline()`（値をリテラルとして展開したもの）で1回だけ再実行します。

- `parameters are not supported for a statement that expands into several`
- `can't be prepared`
- `Parameter expressions within macro`

パラメータのない文や、別の種類のエラーは、そのまま送出されます。リテラルの展開は `render_literal()` が型ごとにエスケープするので、再試行しても SQL インジェクションの危険は増えません。

## 結果の変換

| メソッド | 結果 |
|---|---|
| `fetchall()` / `fetchone()` | DuckDB のタプル |
| `df()` / `pl()` | pandas / polars の DataFrame |
| `fetch_as(into)` / `fetch_one_as(into)` | `into` 型のオブジェクト |

`fetch_as(into)` は `result.rows_into()` を呼びます。

- `into` が `Model` のサブクラスなら、各行を `{カラム名: 値}` にして `into.from_row()` に渡す。モデルにないカラムがあれば `ValueError`
- それ以外（dataclass、NamedTuple、TypedDict、アノテーション付きのクラス）なら、`get_type_hints(into)` でフィールドを調べ、`into(**row)` で作る。フィールドにないカラムがあれば、`.as_()` で別名を付けるよう促す `ValueError`

DuckDB は GEOMETRY のカラムを WKB のバイト列で返します。アノテーションが shapely のジオメトリ型（`| None` を含む）のフィールドや、モデルの GEOMETRY のカラムには、`shapely.from_wkb()` で変換した値が入ります。

INSERT / UPDATE / DELETE で `returning()` を指定していなければ、`fetch_as()` は結果がないことを示す `ValueError` を送出します。

## appender

`db.appender(...)` は、DuckDB のネイティブ appender（`connection.appender(...)`）の型付きラッパー `Appender` を返します。行を INSERT 文にせず、DuckDB に直接バッファリングするので、大量の行を速く書き込めます。

### カラムとキーの決め方

`Appender` を作るとき、次のように書き込むカラムとキーのカラムを決め、ネイティブ appender に `action`、`columns`、`key` として渡します。

| 項目 | 決め方 |
|---|---|
| `columns` | 指定があればそれ。モデルなら、生成カラムとデータベース側デフォルトのあるカラム（`column(default=fn.now())`）を除いたカラム |
| `key` | 指定があればそれ。モデルで `update` / `delete` なら主キー |
| `delete` | キーのカラムだけをバッファリングする |
| `update` / `delete` でキーがない | `ValueError` |

データベース側デフォルトのあるカラムを除くのは、appender が `DEFAULT` を書き込めないためです。除いたカラムは DuckDB が埋めます。逆に、除いたカラムにモデルのインスタンスが値（`DEFAULT` 以外）を持っていると、値が黙って捨てられないように `ValueError` にします。

### 行の変換

`append(row)` は、行を `columns` の順のタプルにしてから `append_row` に渡します。

- `Model` のインスタンスは `to_row()` で辞書にしてから並べる
- マッピングはカラム名で値を取り出す（足りないカラムがあれば `ValueError`）
- シーケンスはそのまま使う
- shapely のジオメトリは WKB に変換する

### フラッシュ

- `with` ブロックが正常に終わると `flush()` し、例外で終わると `clear()` してバッファを捨てる
- `batch_size` を指定すると、その行数ごとに自動で `flush()` する
