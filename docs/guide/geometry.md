# GEOMETRY（shapely）

DuckDB 2.0 のコアには GEOMETRY 型があります。parrotlet では shapely のジオメトリをそのまま値として扱えます。

```python
from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry

from parrotlet import Column, Model, column
from parrotlet import datatype as dt
from parrotlet.functions import spatial as ST


@db.register
class Place(Model, table="places"):
    id: Column[int] = column(primary_key=True)
    geom: Column[BaseGeometry]  # GEOMETRY
    area: Column[BaseGeometry | None] = column(dt.GEOMETRY("OGC:CRS84"), default=None)  # CRS を指定


db.insert(Place).values(Place(id=1, geom=Point(1.5, 2))).execute()
db.select(Place.id).from_(Place).where(Place.geom == Point(1.5, 2)).fetchall()
db.select(ST.st_distance(Place.geom, Point(0, 0))).from_(Place).fetchall()
db.from_(Place).fetch(Place)[0].geom  # shapely の Point
```

- **値の渡し方**：値として渡したジオメトリは WKB に変換され、`CAST(? AS GEOMETRY)` としてバインドされます。
- **リストや構造体の中**：DuckDB はリストや構造体の中のジオメトリをパラメータとしてバインドできないため、そうした値はリテラルとして展開されます。
- **結果の受け取り**：DuckDB は GEOMETRY を WKB の bytes で返します。`fetch(Model)` や、フィールドに shapely の型を付けたデータクラスでは、自動で shapely のオブジェクトに変換されます。
- **spatial 拡張の型と関数**：`dt.POINT_2D` などの型や `ST.*` の関数を使うと、spatial 拡張が自動で読み込まれます。
