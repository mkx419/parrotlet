# parrotlet

**parrotlet** は、DuckDB 用の型安全な SQL クエリビルダーです（Python 3.14 以上）。

```python
from parrotlet import Column, Database, Model, column
from parrotlet import functions as F

db = Database()


@db.register
class User(Model, table="users"):
    id: Column[int] = column(primary_key=True)
    name: Column[str]
    age: Column[int | None] = column(default=None)


db.insert(User).values(User(id=1, name="alice", age=30)).execute()
db.select(User.name, F.upper(User.name)).from_(User).where(User.age >= 20).fetchall()
# [('alice', 'ALICE')]
```

## 特徴

型安全
:   式は `Expr[T]` で SQL 型を持ちます。`User.name > 3` や `F.upper(User.age)`、`where(User.name)` は、実行する前に pyright などの型チェッカーがエラーにします。詳しくは[型安全](guide/typing.md)を参照してください。

モデル = テーブル定義 + 行
:   SQLModel のように、1つのクラスでテーブル定義と dataclass ライクな行型を兼ねます。クラス属性（`User.age`）はクエリ用の型付きカラム、インスタンス属性（`user.age`）は値です。詳しくは[モデル](guide/models.md)を参照してください。

接続を持ち回らない
:   `db.select(...)` のように `Database` から作ったステートメントは、`.fetchall()` や `.fetch(User)` でそのまま実行できます。`@db.register` を付ければ CREATE TABLE も自動です。詳しくは [Database](guide/database.md) を参照してください。

DuckDB の機能を網羅
:   PIVOT / UNPIVOT、MERGE、QUALIFY、`COLUMNS(...)`、`* EXCLUDE / REPLACE / RENAME / LIKE`、ASOF / SEMI / ANTI JOIN、リスト内包表記、ラムダ、COPY、マクロ、ATTACH などに対応しています。詳しくは [DuckDB 固有の機能](guide/duckdb.md)を参照してください。

型付きの関数
:   DuckDB の関数カタログから生成した、約 1,200 個の型付き関数（spatial 拡張を含む）を用意しています。詳しくは[関数](guide/functions.md)を参照してください。

appender
:   DuckDB の appender で、大量の行を高速に insert / upsert / update / delete できます。詳しくは [Database](guide/database.md#appender) を参照してください。

拡張機能の自動導入
:   spatial の関数や型を使うと、その拡張機能を自動で INSTALL / LOAD します。

安全
:   値はすべて `?` パラメータとしてバインドされます。DDL など DuckDB がパラメータを受け付けない場所では、エスケープ済みのリテラルとして展開されます。識別子は常にクォートされます。

## インストール

```bash
uv add parrotlet
```

依存パッケージは `duckdb`（2.0 以上）と `shapely` です。
