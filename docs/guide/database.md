# Database

`Database` は DuckDB の接続をラップするクラスです。`Database` から作ったステートメントはその接続に結びつき（バインドされ）、接続を渡さずに実行できます。

## 接続を開く

```python
import duckdb
from parrotlet import Database

db = Database()  # インメモリ（":memory:"）
db = Database("app.duckdb")  # ファイル（なければ作成）
db = Database("app.duckdb", read_only=True)  # 読み取り専用
db = Database(config={"threads": 4, "memory_limit": "4GB"})  # DuckDB の設定
db = Database(connection=duckdb.connect())  # 既存の接続を使う
db = Database(extensions=["spatial", "httpfs"])  # 起動時に拡張機能を読み込む
db = Database(auto_install=False)  # 拡張機能の自動導入を無効にする
```

| 引数 | 既定値 | 意味 |
|---|---|---|
| `path` | `":memory:"` | データベースファイルのパス（`str` または `pathlib.Path`） |
| `read_only` | `False` | 読み取り専用で開く |
| `config` | `None` | `duckdb.connect()` に渡す設定 |
| `extensions` | `()` | 接続時に INSTALL / LOAD する拡張機能 |
| `auto_install` | `True` | クエリが必要とする拡張機能を自動で導入する（[後述](#extensions)） |
| `connection` | `None` | 既存の DuckDB 接続。指定すると `path` などは無視される |

使い終わったら `db.close()` で閉じます。`with` 文を使うと、ブロックを抜けるときに自動で閉じます。

```python
with Database("app.duckdb") as db:
    ...
```

DuckDB の接続そのものは `db.connection` で取り出せます。parrotlet にない機能を使うときは、こちらを直接使ってください。

## バインドされたステートメント

次のメソッドは、同じ名前のトップレベル関数と同じステートメントを、`db` にバインドして返します。

| メソッド | 作るステートメント |
|---|---|
| `db.select(...)` / `db.from_(...)` | SELECT（[SELECT](select.md)） |
| `db.insert(table)` | INSERT（[DML](dml.md#insert)） |
| `db.update(table)` | UPDATE |
| `db.delete(table)` | DELETE |
| `db.merge_into(table)` | MERGE |
| `db.pivot(source)` / `db.unpivot(source)` | PIVOT / UNPIVOT |
| `db.create_table(table)` | CREATE TABLE |
| `db.truncate(table)` | TRUNCATE |

```python
db.select(User.name).from_(User).where(User.age > 20).fetchall()
db.insert(User).values(User(id=3, name="carol")).execute()
db.update(User).set({User.age: User.age + 1}).where(User.id == 3).execute()
db.delete(User).where(User.age.is_null()).returning(User.id).fetchall()
```

バインドは引き継がれます。`db.select(...)` から `.where()` や `.union()` を何度つないでも、最後まで同じ `db` で実行されます。

## 実行するメソッド

どのステートメントにも、次のメソッドがあります。

| メソッド | 戻り値 |
|---|---|
| `.execute()` | DuckDB のカーソル（`DuckDBPyConnection`） |
| `.fetchall()` | タプルのリスト |
| `.fetchone()` | 最初の1行のタプル、または `None` |
| `.fetch_as(into)` | `into` 型のオブジェクトのリスト（[結果の変換](results.md)） |
| `.fetch_one_as(into)` | `into` 型のオブジェクト、または `None` |
| `.df()` / `.pl()` | pandas / polars の DataFrame（各パッケージが必要） |

どの接続で実行するかは、次の順で決まります。

1. 引数で渡した接続：`stmt.fetchall(con)`
2. ステートメントがバインドされている `Database`
3. DuckDB のデフォルト接続（`duckdb.default_connection()`）

## その他の場所で作ったステートメント

トップレベルの関数（`create_view()`、`select()` など）で作ったステートメントは、どの `Database` にもバインドされていません。`db.execute()` で実行するか、`db.bind()` でバインドします。

```python
from parrotlet import create_view, select

db.execute(create_view("adults", select(User).from_(User).where(User.age >= 20)))

q = select(User.id).from_(User)  # どこかで作ったクエリ
db.bind(q).fetchall()
db.fetch_as(q, User)  # db.bind(q).fetch_as(User) と同じ
```

`db.execute()` は次のものを受け付け、DuckDB のカーソルを返します。

| 渡すもの | 例 |
|---|---|
| ステートメント（`Node`） | `db.execute(drop_table("t"))` |
| コンパイル済みの `Query` | `db.execute(Query("SELECT ?", (1,)))` |
| t-string | `db.execute(t"SELECT {x}")` |

## 生の SQL

Python 3.14 のテンプレート文字列（t-string）で、生の SQL を書けます。埋め込んだ値はパラメータになるので、SQL インジェクションの心配はありません。

```python
min_age = 20
db.sql(t"SELECT name FROM users WHERE age >= {min_age}").fetchall()
# SELECT name FROM users WHERE age >= ?   params: (20,)
```

式やステートメントを埋め込むこともできます。

```python
db.sql(t"SELECT {fn.upper(User.name)} FROM users").fetchall()
db.sql(t"SELECT count(*) FROM ({select(User.id).from_(User)})").fetchone()
```

!!! warning "f-string は使わない"
    `db.sql(f"... {x}")` のように f-string を使うと、値が SQL に直接埋め込まれます。`db.sql()` は t-string（`t"..."`）だけを受け付けます。

## モデルの登録

```python
@db.register  # その場で CREATE TABLE IF NOT EXISTS を実行
class User(Model, table="users"): ...
```

`db.register(User)` と書いても同じです。`IF NOT EXISTS` なので、何度呼んでも問題ありません。既存のテーブルの定義は変更しないので、カラムを追加したときは [ALTER TABLE](ddl.md#alter-table) を使ってください。

## トランザクション {#transactions}

DuckDB は、各ステートメントを自動でコミットします。複数の文を1つのトランザクションにまとめるには、`begin()`、`commit()`、`rollback()` を実行します。

```python
from parrotlet import begin, commit, rollback

db.execute(begin())
try:
    db.update(User).set(age=User.age + 1).where(User.id == 1).execute()
    db.insert(Order).values(Order(id=99, user_id=1, amount=Decimal(10))).execute()
    db.execute(commit())
except Exception:
    db.execute(rollback())
    raise
```

```sql
BEGIN TRANSACTION
...
COMMIT
```

DuckDB の接続オブジェクトの `db.connection.begin()` / `commit()` / `rollback()` を使っても同じです。

## スレッドと接続

DuckDB の1つの接続は、複数のスレッドから同時に使えません。スレッドごとに `db.connection.cursor()` で接続を分け、`Database(connection=...)` でラップしてください。

```python
def worker(db: Database) -> None:
    local = Database(connection=db.connection.cursor())
    local.select(fn.count()).from_(User).fetchone()
```

## appender

DuckDB の appender は、行をバッファにためて、まとめてテーブルに書き込みます。1行ずつ INSERT するより大幅に高速です。

```python
with db.appender(User) as app:  # ブロックを正常に抜けると flush される
    app.append(User(id=1, name="alice"))
    app.extend(User(id=i, name=f"u{i}") for i in range(2, 100_000))
```

ブロックの中で例外が起きると、バッファの行は書き込まずに捨てられます。

### 動作の種類（action）

```python
# 主キーで INSERT、または置き換え
with db.appender(User, action="upsert") as app:
    app.extend(users)

# キーで UPDATE。name は columns にないので使われない
with db.appender(User, action="update", columns=[User.id, User.age]) as app:
    app.append(User(id=2, name="ignored", age=31))

# キーで DELETE。キー（id）以外の値は使われない
with db.appender(User, action="delete") as app:
    app.append(User(id=3, name="ignored"))
```

| `action` | 動作 | キー |
|---|---|---|
| `"insert"`（既定） | 行を追加する | 不要 |
| `"upsert"` | 主キー・一意制約が同じ行があれば置き換え、なければ追加する | テーブルの主キー・一意制約（`key=` は指定しない） |
| `"update"` | キーが同じ行の `columns` を更新する | 必要 |
| `"delete"` | キーが同じ行を削除する | 必要 |

### 引数

| 引数 | 意味 |
|---|---|
| `columns` | 書き込むカラム。モデルの場合の既定は、生成カラムと DB 側の既定値（`column(default=fn.now())`）を持つカラムを除いた全カラム。モデル以外のテーブルで dict の行を渡すときは必須 |
| `key` | update / delete で行を特定するキー。モデルの場合は主キーが既定 |
| `batch_size` | この行数ごとに自動で flush する |

### 渡せる行

```python
db.sql(t"CREATE TABLE events (ts TIMESTAMP, kind VARCHAR)")
app = db.appender("events", columns=["ts", "kind"], batch_size=10_000)
app.append((now, "click"))  # columns の順に並べたシーケンス
app.append({"ts": now, "kind": "view"})  # dict（カラム名 → 値）
app.flush()  # 明示的に書き込む
app.clear()  # バッファを書き込まずに捨てる
```

- モデルのテーブルには、モデルのインスタンスも渡せます。
- shapely のジオメトリは、WKB に変換して書き込まれます。
- 型チェック上、`db.appender(User)` は `Appender[User]` なので、別のモデルのインスタンスを渡すと型エラーになります。
- `Database` を使わずに、`Appender(con, User)` と直接作ることもできます。

### appender の制限

- `action="upsert"` に `key=` を渡すと `ValueError` になります。upsert はテーブルの主キー・一意制約で行を突き合わせます。
- appender は `DEFAULT` を書き込めません。DB 側の既定値を持つカラムは、既定では `columns` から除かれ、DuckDB が値を埋めます。そのカラムにインスタンスが値を持っていると、値が黙って捨てられないように `ValueError` になります。値も書き込みたいときは `columns=` で明示してください。
- 同じ接続で `fetchone()` などの結果を最後まで読んでいないと、flush が `ResourceInUseException` で失敗します（[トラブルシューティング](troubleshooting.md#resource-in-use)）。

## 拡張機能の自動導入 {#extensions}

`Database` は、クエリが必要とする拡張機能を自動で `INSTALL` / `LOAD` します。

- **型付きの関数と型**：`parrotlet.functions.spatial` の関数や、`qlt.Point2D` などの型は、必要な拡張機能を自分で把握しています。実行する前に読み込まれます。
- **型なしの関数**：`func.<name>(...)` などで DuckDB が「この関数は X 拡張機能にある」というエラーを返したときは、その拡張機能を入れて1回だけ再実行します。

この動作は `Database(auto_install=False)` で無効にできます。オフライン環境などで拡張機能を事前に入れておく場合は、`Database(extensions=[...])` か [`install()` / `load()`](duckdb.md#utility) を使ってください。

`Database` を使わずに `stmt.execute(con)` で実行した場合も、同じように自動導入されます。
