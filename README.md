# parrotlet

DuckDB 用の、型安全な SQL クエリビルダーです（Python 3.14+）。

- **型安全**：式は `Expr[T]` で SQL 型を持ちます。演算子や関数の引数・戻り値を pyright などの型チェッカーで検査できます。
- **モデル = テーブル定義 + 行**：SQLModel のように、1つのクラスでテーブル定義と dataclass ライクな行型を兼ねます。
- **DuckDB の機能を網羅**：PIVOT、MERGE、QUALIFY、`COLUMNS(...)`、`* EXCLUDE / REPLACE / RENAME`、ASOF JOIN、リスト内包表記、COPY、マクロなどに対応しています。
- **関数を型付きで用意**：DuckDB の関数（spatial 拡張を含む約 1,200 個）を、カタログから生成した型付き関数として用意しています。
- **appender**：DuckDB の appender で、大量の行を高速に insert / upsert / update / delete できます。
- **拡張機能の自動導入**：spatial などの拡張機能は、必要になった時点で自動で INSTALL / LOAD します。

```python
import datetime
from parrotlet import Column, Database, Model, column
import parrotlet.functions as fn
db = Database("app.duckdb")


@db.register  # CREATE TABLE IF NOT EXISTS
class User(Model, table="users"):
    id: Column[int] = column(primary_key=True)
    name: Column[str]
    age: Column[int | None] = column(default=None)
    joined: Column[datetime.datetime] = column(default=fn.now())


db.insert(User).values(User(id=1, name="alice", age=30), User(id=2, name="bob")).execute()

with db.appender(User) as app:  # 大量の行は appender で高速に投入
    app.extend(User(id=i, name=f"user{i}") for i in range(3, 10_000))

db.select(User.name, fn.upper(User.name)).from_(User).where(User.age >= 20).fetchall()
db.from_(User).where(User.name.like("a%")).fetch_as(User)  # list[User]

User.name > 3  # 型エラー：VARCHAR と数値は比較できない
fn.upper(User.age)  # 型エラー：upper は VARCHAR を取る
```

## ドキュメント

| 内容 | 場所 |
|---|---|
| 使い方（はじめに、モデル、式、SELECT、DML、DDL、関数、DuckDB 固有の機能など） | [`docs/guide/`](docs/guide/getting-started.md) |
| 内部設計・動作原理（SQL の組み立て、型安全の仕組み、モデル、実行、関数の生成） | [`docs/internals/`](docs/internals/index.md) |
| API リファレンス（docstring から生成） | [`docs/reference/`](docs/reference/index.md) |

使い方ガイド・内部設計・API リファレンスは [Zensical](https://zensical.org/)（mkdocstrings で API リファレンスを生成）でビルドします。設定は `zensical.toml` です。

```bash
uv run --group docs zensical serve
```

## 開発

```bash
uv run pytest
```

```bash
uvx ruff check src tests scripts
```

```bash
uvx pyright src tests scripts
```

```bash
uvx ty check src tests scripts
```

関数モジュール（`src/parrotlet/functions/_core.py` など）は、DuckDB の関数カタログから生成しています。DuckDB を更新したら再生成してください。

```bash
uv run python scripts/generate_functions.py
```
