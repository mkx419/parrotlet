# 結果の変換

## 結果を受け取るメソッド

| メソッド | 戻り値 | 用途 |
|---|---|---|
| `.fetchall()` | `list[tuple]` | 手早く全行を取る |
| `.fetchone()` | <code>tuple &#124; None</code> | 1行だけ取る |
| `.fetch_as(into)` | `list[into]` | 型付きのオブジェクトで受け取る |
| `.fetch_one_as(into)` | <code>into &#124; None</code> | 1行だけ型付きで受け取る |
| `.df()` | pandas の DataFrame | 分析（pandas が必要） |
| `.pl()` | polars の DataFrame | 分析（polars が必要） |
| `.execute()` | DuckDB のカーソル | DuckDB の API を直接使う（`.arrow()`、`.fetchmany()` など） |

`fetchall()` と `fetchone()` は、DuckDB と同じくタプルを返します。指定した型のオブジェクトで受け取るときは、名前が `_as` で終わる `fetch_as()` と `fetch_one_as()` を使います。

## fetch_as：型付きのオブジェクトにする

`fetch_as(into)` は、各行を `into` 型のオブジェクトに変換します。カラム名とフィールド名で対応付けます。

```python
from dataclasses import dataclass
from typing import NamedTuple, TypedDict


@dataclass
class Row:
    name: str
    age: int | None


class Pair(NamedTuple):
    country: str | None
    n: int


class NameOnly(TypedDict):
    name: str


db.select(User.name, User.age).from_(User).fetch_as(Row)
# [Row(name='alice', age=30), Row(name='bob', age=None)]

q = db.select(User.country, fn.count().as_("n")).from_(User).group_by(User.country)
q.fetch_as(Pair)
# [Pair(country='JP', n=1), Pair(country=None, n=1)]

db.select(User.name).from_(User).fetch_as(NameOnly)
# [{'name': 'alice'}, {'name': 'bob'}]

db.from_(User).fetch_as(User)  # モデルのインスタンス
db.from_(User).where(User.id == 99).fetch_one_as(User)  # None
```

型チェッカーは、`fetch_as(Row)` の戻り値を `list[Row]` と推論します。

### 変換先と対応付け

| 変換先 | 対応付け |
|---|---|
| モデル（`Model` のサブクラス） | SQL のカラム名とモデルのカラムを対応付ける（`column(name=...)` の名前も考慮）。結果にないカラムは `None` になる |
| データクラス・NamedTuple・TypedDict・型注釈付きのクラス | 型注釈のフィールド名とカラム名で対応付け、`into(**row)` で作る（pydantic の `BaseModel` なども使える） |

- **フィールドにないカラム**：`ValueError` になります。式には `.as_("name")` で別名を付けて、フィールド名と合わせてください。

    ```python
    db.select(User.name, fn.upper(User.name)).from_(User).fetch_as(Row)
    # ValueError: Columns ['upper(users."name")'] have no matching field on Row;
    #   alias them with .as_()
    ```

- **結果にないフィールド**：データクラスでは、既定値のないフィールドが足りないと `TypeError` になります。
- **ジオメトリ**：フィールドが shapely のジオメトリ型なら、WKB を shapely のオブジェクトに変換します。
- **値の変換**：それ以外の値は DuckDB が返した Python の値のまま渡されます（型注釈に合わせた変換はしません）。

### INSERT / UPDATE / DELETE の結果

データを変更する文から結果を受け取るには、`.returning(...)` を付けます。

```python
ins = db.insert(User).values(User(id=6, name="f", age=20))
ins.returning(User.name, User.age).fetch_as(Row)
# [Row(name='f', age=20)]

upd = db.update(User).set(age=User.age + 1).where(User.id == 1)
upd.returning(User.age).fetchall()
# [(31,)]
```

`.returning()` のない文に `fetch_as()` を使うと、実行する前に `ValueError` になります。

## DataFrame

```python
# pandas
db.select(User.country, fn.count().as_("n")).from_(User).group_by_all().df()

db.from_(User).pl()  # polars
db.from_(User).execute().arrow()  # pyarrow（DuckDB のカーソルのメソッド）
```

## 大きな結果

`fetchall()` や `fetch_as()` は全行をメモリに読み込みます。大きな結果を少しずつ処理するときは、`.execute()` で DuckDB のカーソルを取り、`fetchmany()` を使ってください。

```python
cursor = db.from_(Order).execute()
while rows := cursor.fetchmany(10_000):
    process(rows)
```
