# トラブルシューティング

よくあるエラーと、その原因・対処です。

## Python の書き方に関するもの

### `TypeError: SQL expressions have no truth value`

式を Python の真偽値として使っています。

```python
db.from_(User).where(User.age > 20 and User.country == "JP")  # NG
if User.age > 20:
    ...  # NG
```

`and` / `or` / `not` の代わりに `&` / `|` / `~`（または `and_()` / `or_()` / `not_()`）を使ってください。

```python
db.from_(User).where((User.age > 20) & (User.country == "JP"))
db.from_(User).where(User.age > 20, User.country == "JP")  # 複数の引数は AND
```

### 条件が意図と違う SQL になる

`&` `|` は比較演算子より優先順位が高いので、比較を括弧で囲まないと違う意味になります。

```python
User.age > 20 & (User.name == "a")  # NG: User.age > (20 AND (name = 'a'))
(User.age > 20) & (User.name == "a")  # OK
```

型チェッカーは、この間違いを `Operator "&" not supported` として検出します。

### `TypeError: ... is not iterable`

式を `for` や `list()`、`*` で展開しようとしています。`*` で展開できるのは `columns(...)` だけです（`fn.coalesce(*columns("num_.*"))`）。

### `TypeError: in_() expects an iterable of values, not a string`

`User.country.in_("JP")` のように文字列を渡しています。`in_(["JP"])` とリストにしてください。

### t-string の `{}` でエラーになる

t-string（`t"..."`）の中では `{...}` が値の埋め込みになります。SQL の中に JSON などの `{` `}` をそのまま書くと、その一部が値として解釈され、`Parameter/argument count mismatch`（DuckDB）や `ValueError: Invalid format specifier`（Python）などのエラーになります。

`{` `}` は `{{` `}}` と重ねるか、値をパラメータとして渡してください。

```python
db.sql(t"SELECT '{'a': 1}'::JSON")  # NG
db.sql(t"SELECT '{{\"a\": 1}}'::JSON")  # OK（括弧を重ねる）
doc = '{"a": 1}'
db.sql(t"SELECT {doc}::JSON")  # OK（パラメータになる）
```

## モデルに関するもの

### `TypeError: Cannot infer a DuckDB type for ...`

アノテーションから DuckDB の型を推論できません。`column(qlt.Struct(...))` のように型を明示してください（[データ型](datatypes.md)）。

### 型チェッカーが `age: Column[int | None] = None` をエラーにする

`Column[...]` 型の属性に `None` を代入しているとみなされます。`column(default=None)` と書いてください。

### `TypeError: User() missing keyword argument 'name'`

既定値のないカラムの値を渡していません。省略したいカラムには `column(default=...)` を付けてください。

### INSERT で `NOT NULL constraint failed: users.tags`

`column(default_factory=list)` は Python 側だけの既定値で、SQL の `DEFAULT` にはなりません。そのカラムを省いた INSERT（`insert(User, ["id", "name"])` や dict の行）では値が入らず、NOT NULL 制約に違反します。

- モデルのインスタンスで INSERT する（`insert(User).values(User(...))`）と、Python 側の既定値（`[]`）が入ります。
- カラムを指定して INSERT するときは、そのカラムも含めてください。
- appender はモデルの全カラムを書き込むので、この問題は起きません。

## クエリに関するもの

### `ValueError: Columns [...] have no matching field on Row`

`fetch_as(Row)` で、結果のカラムに対応するフィールドがありません。式に `.as_("name")` で別名を付けてください。

```python
db.select(User.name, fn.upper(User.name).as_("upper_name")).from_(User).fetch_as(Row)
```

### `ValueError: This statement returns no rows; add .returning(...)`

INSERT / UPDATE / DELETE に `.fetch_as()` を使っています。`.returning(...)` を付けるか、`.execute()` を使ってください。

### `ValueError: Give the table function an alias (.as_()) to reference its columns`

別名のないテーブル関数やファイルのカラムを参照しています。`fn.table.range(10).as_("r")` や `file("x.csv").as_("f")` のように別名を付けてください。

### `TypeError: Use .subquery(alias) to put a statement in FROM`

ステートメントをそのまま FROM や JOIN に渡しています。`.subquery("s")` で別名を付けてください。

### `==` で型の違う値を比べても型エラーにならない

`User.id == "1"` は、型チェッカー上 `bool` として扱われ、エラーになりません（Python の `__eq__` の仕様のため）。ただし `where()` などは `Expr[Boolean]` しか受け付けないので、そこで検出されます。

## 実行に関するもの

### `ResourceInUseException: connection has an unfinished result` {#resource-in-use}

同じ接続で、前のクエリの結果を最後まで読んでいない状態で、appender の flush などをしました。`fetchone()` は1行だけ読むので、結果が残ります。

```python
db.select(fn.count()).from_(User).fetchone()
with db.appender(User) as app:  # flush で ResourceInUseException
    ...
```

- 1行だけ欲しいときは、`fetch_one_as(...)` か `fetchall()` を使う（どちらも結果を最後まで読みます）。
- または、別の文を実行してから appender を使う。
- または、appender 用に `db.connection.cursor()` で別の接続を作る。

### `Constraint Error: Violates foreign key constraint ... still referenced`

DuckDB の制限で、外部キーから参照されている行を、`MERGE` の UPDATE などで書き換えると失敗することがあります。通常の `UPDATE` や `INSERT ... ON CONFLICT DO UPDATE`、appender の upsert は動きます。

### `ValueError: The upsert action matches on the table's primary key / unique constraints; omit key=`

appender の `action="upsert"` に `key=` を渡しています。upsert はテーブルの主キー・一意制約で行を突き合わせるので、キーは指定しないでください。

### 拡張機能のダウンロードに失敗する

spatial などの拡張機能は、初めて使うときに自動でダウンロードされます。オフライン環境では、事前に `INSTALL` しておくか、`Database(auto_install=False)` で自動導入を無効にしてください（[Database](database.md#extensions)）。

### パラメータを使えないというエラー

`parameters are not supported for a statement that expands into several` などのエラーは、parrotlet が自動で値をリテラルにして再実行します。それでも失敗する場合は、`q.sql_inline` の SQL を確認してください。

### SQL を確認したい

```python
q.sql  # パラメータ付き
q.params
q.sql_inline  # 値を埋め込んだもの
```

`q.sql_inline` を DuckDB の CLI に貼り付けると、parrotlet を通さずに挙動を確認できます。
