# 結果の変換

`fetch(into)` は結果の各行を変換します。カラム名とフィールド名で対応付けます。

```python
from dataclasses import dataclass
from typing import NamedTuple, TypedDict


@dataclass
class Total:
    name: str
    total: Decimal


class Pair(NamedTuple):
    country: str | None
    n: int


q.fetch(Total)  # list[Total]
q.fetch_one(Total)  # Total | None
select(User).from_(User).fetch(User)  # モデルのインスタンス
insert(User).values(...).returning(User.id, User.name).fetch(UserRow)
```

| 変換先 | 対応付け |
|---|---|
| モデル（`Model` のサブクラス） | SQL のカラム名とモデルのカラムを対応付け、`name=` で付けた別名も考慮する |
| データクラス・NamedTuple・TypedDict・型注釈付きのクラス | 型注釈のフィールド名とカラム名で対応付け、`into(**row)` で生成する（pydantic の `BaseModel` も可） |

- **ジオメトリの変換**：フィールドが shapely のジオメトリ型（`BaseGeometry`、`Point | None` など）の場合は、WKB を自動で shapely のオブジェクトに変換します。
- **対応するフィールドがないカラム**：エラーになります。`.as_("name")` で名前を合わせてください。
- **RETURNING のない DML**：INSERT / UPDATE / DELETE に `fetch` を使うとエラーになります。`.returning(...)` を付けてください。

そのほか、`.fetchall()`、`.fetchone()`、`.df()`（pandas）、`.pl()`（polars）、`.execute()`（DuckDB のカーソル）も使えます。
