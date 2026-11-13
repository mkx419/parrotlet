# GEOMETRY（shapely）

DuckDB 2.0 のコアには GEOMETRY 型があります。parrotlet では、shapely のジオメトリをそのまま値として扱えます。

## モデルのカラム

```python
from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry

from parrotlet import Column, Model, column
import parrotlet.type as qlt
@db.register
class Place(Model, table="places"):
    id: Column[int] = column(primary_key=True)
    name: Column[str]
    geom: Column[BaseGeometry]  # GEOMETRY
    # CRS を指定
    area: Column[Polygon | None] = column(qlt.Geometry("OGC:CRS84"), default=None)
```

- アノテーションが shapely のジオメトリの型（`BaseGeometry`、`Point`、`Polygon` など）なら、カラムは `GEOMETRY` になります。
- CRS（座標参照系）を指定するときは、`qlt.Geometry("OGC:CRS84")` のように型を明示します。
- クエリでの型は `ColumnRef[Geometry]` です。

## 値を書き込む・読む

```python
db.insert(Place).values(Place(id=1, name="station", geom=Point(139.767, 35.681))).execute()

with db.appender(Place) as app:  # appender でも同じように書ける
    app.append(Place(id=2, name="park", geom=Point(139.700, 35.690)))

place = db.from_(Place).where(Place.id == 1).fetch_one_as(Place)
place.geom  # <POINT (139.767 35.681)>（shapely のオブジェクト）
```

| 場面 | 動作 |
|---|---|
| パラメータとして渡す | WKB に変換し、`CAST(? AS GEOMETRY)` の `?` に渡す |
| リストや構造体の中にある | DuckDB がパラメータとして受け取れないので、リテラル（`'\x01...'::BLOB::GEOMETRY`）として埋め込む |
| appender | WKB に変換して書き込む |
| `fetch_as(Model)` / shapely 型のフィールドを持つデータクラス | DuckDB が返す WKB を `shapely.from_wkb()` で変換する |
| `fetchall()` | WKB の `bytes` のまま |

## 条件と関数

```python
station = Point(139.767, 35.681)

db.select(Place.name).from_(Place).where(Place.geom == station)
# WHERE ("places"."geom" = CAST(? AS GEOMETRY))

distance = fn.spatial.st_distance(Place.geom, station)
db.select(Place.name, distance.as_("d")).from_(Place).order_by("d")

db.select(Place.name).from_(Place).where(fn.spatial.st_dwithin(Place.geom, station, 0.01))
db.select(fn.spatial.st_as_text(Place.geom)).from_(Place)  # WKT の文字列
db.select(fn.spatial.st_area(fn.spatial.st_geom_from_text("POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))")))
```

- `fn.spatial.*` の関数は、spatial 拡張が必要なものは実行時に自動で読み込まれます。
- DuckDB 2.0 のコアに入った `ST_*` 関数（`st_as_text` など）は、拡張なしで動きます。
- spatial 拡張の型（`qlt.Point2D`、`qlt.Box2D` など）を使うと、spatial 拡張が自動で読み込まれます。

## 結果をデータクラスで受け取る

```python
from dataclasses import dataclass


@dataclass
class Nearby:
    name: str
    geom: Point
    d: float


distance = fn.spatial.st_distance(Place.geom, station)
db.select(Place.name, Place.geom, distance.as_("d")).from_(Place).fetch_as(Nearby)
```

フィールドの型が shapely のジオメトリ（`Point | None` なども含む）なら、自動で shapely のオブジェクトに変換されます。
