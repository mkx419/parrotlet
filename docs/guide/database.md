# Database

`Database` は DuckDB の接続を包むクラスです。`Database` から作ったステートメントは、その接続に結びつき（バインドされ）、接続を渡さずに実行できます。

```python
from parrotlet import Database

db = Database()  # インメモリ
db = Database("app.duckdb")  # ファイル
db = Database("app.duckdb", read_only=True)
db = Database(config={"threads": 4})
db = Database(connection=duckdb.connect())  # 既存の接続を使う
db = Database(extensions=["spatial"])  # 起動時に拡張機能を読み込む

with Database("app.duckdb") as db:  # 抜けるときに close()
    ...
```

## バインドされたステートメント

`db.select` / `db.from_` / `db.insert` / `db.update` / `db.delete` / `db.merge_into` / `db.pivot` / `db.unpivot` / `db.create_table` / `db.truncate` は、通常の同名関数と同じものを、`db` にバインドして返します。

```python
db.select(User.name).from_(User).where(User.age > 20).fetchall()
db.insert(User).values(User(id=3, name="carol")).execute()
db.update(User).set({User.age: User.age + 1}).where(User.id == 3).execute()
db.delete(User).where(User.age.is_null()).returning(User.id).fetchall()
```

ステートメントを実行するメソッドは次のとおりです。

| メソッド | 戻り値 |
|---|---|
| `.execute()` | DuckDB のカーソル（`DuckDBPyConnection`） |
| `.fetchall()` / `.fetchone()` | タプルのリスト / タプル |
| `.fetch(into)` / `.fetch_one(into)` | モデルやデータクラスのリスト / 1件（[結果の変換](results.md)） |
| `.df()` / `.pl()` | pandas / polars の DataFrame |

それ以外の場所で作ったステートメントは、`db.execute(stmt)` で実行するか、`db.bind(stmt)` でバインドします。

```python
from parrotlet import create_view, select

db.execute(create_view("adults", select(User).from_(User).where(User.age >= 20)))
db.bind(select(User.id).from_(User)).fetchall()
```

生の SQL は t-string で書けます。埋め込んだ値はパラメータになります。

```python
min_age = 20
db.sql(t"SELECT name FROM users WHERE age >= {min_age}").fetchall()
```

## モデルの登録

```python
@db.register  # その場で CREATE TABLE IF NOT EXISTS を実行
class User(Model, table="users"): ...
```

`db.register(User)` と書いても同じです。何度呼んでも問題ありません。

## appender

DuckDB の appender で、大量の行をバッファしてまとめて書き込みます。1行ずつ INSERT するより大幅に高速です。

```python
with db.appender(User) as app:  # ブロックを正常に抜けると flush される（例外時は破棄）
    app.append(User(id=1, name="alice"))
    app.extend(User(id=i, name=f"u{i}") for i in range(2, 100_000))

with db.appender(User, action="upsert") as app:  # 主キーで INSERT または置き換え
    app.extend(users)

with db.appender(User, action="update", columns=[User.id, User.age]) as app:  # キーで UPDATE
    app.append(User(id=2, name="ignored", age=31))

with db.appender(User, action="delete") as app:  # キーで DELETE（キー以外の値は使われない）
    app.append(User(id=3, name="ignored"))

app = db.appender("events", columns=["ts", "kind"], batch_size=10_000)  # 1万行ごとに自動で flush
app.append((now, "click"))
app.append({"ts": now, "kind": "view"})
app.flush()
```

| 引数 | 意味 |
|---|---|
| `action` | `"insert"`（既定）/ `"upsert"` / `"update"` / `"delete"` |
| `columns` | 書き込むカラム。モデルの場合は、生成カラムと DB 側の既定値（`column(default=F.now())`）を持つカラムを除いた全カラムが既定 |
| `key` | update / delete / upsert のキー。モデルの場合は主キーが既定 |
| `batch_size` | この行数ごとに自動で flush する |

- 渡せる行は、モデルのインスタンス、dict（カラム名 → 値）、`columns` の順に並べたシーケンスです。
- shapely のジオメトリは WKB に変換されます。
- 型チェック上、`db.appender(User)` は `Appender[User]` を返すので、別のモデルのインスタンスを渡すと型エラーになります。
- `Database` を使わずに、`Appender(con, User)` と直接作ることもできます。

## 拡張機能の自動導入

`Database` は、クエリが必要とする拡張機能を自動で `INSTALL` / `LOAD` します。

- **型付き関数・型**：`parrotlet.functions.spatial` の関数や、`dt.POINT_2D` などの型は、必要な拡張機能を自分で把握しています。実行前に読み込まれます。
- **型なしの関数**：`func.<name>(...)` のような型なしの関数で、DuckDB が「〜は X 拡張機能にある」というエラーを返した場合は、その拡張機能を入れて1回だけ再実行します。

この動作は `Database(auto_install=False)` で無効にできます。`Database` を使わずに `stmt.execute(con)` で実行した場合も、同じように自動導入されます。
