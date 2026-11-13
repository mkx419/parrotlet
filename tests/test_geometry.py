import duckdb
import shapely
from shapely.geometry import LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from parrotlet import Column, Model, col, column, create_table, datatype, insert, lit, select, val

point = Point(1.5, 2)
square = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])


def fetch_geometry(con: duckdb.DuckDBPyConnection, q: object) -> object:
    row = q.execute(con).fetchone()  # type: ignore[attr-defined]
    assert row is not None
    return shapely.from_wkb(row[0])


def test_geometry_param(con: duckdb.DuckDBPyConnection) -> None:
    q = select(val(point))
    assert q.sql == "SELECT CAST(? AS GEOMETRY)"
    assert q.params == (point.wkb,)
    assert con.execute("SELECT typeof(CAST(? AS GEOMETRY))", [point.wkb]).fetchone() == ("GEOMETRY",)
    assert fetch_geometry(con, q) == point


def test_geometry_literal(con: duckdb.DuckDBPyConnection) -> None:
    q = select(lit(square))
    assert q.params == ()
    assert q.sql.endswith("'::BLOB::GEOMETRY")
    assert fetch_geometry(con, q) == square


def test_nested_geometry_is_inlined(con: duckdb.DuckDBPyConnection) -> None:
    q = select(val([point, LineString([(0, 0), (1, 1)])]))
    assert q.params == ()
    row = q.execute(con).fetchone()
    assert row is not None
    assert [shapely.from_wkb(g) for g in row[0]] == [point, LineString([(0, 0), (1, 1)])]


class Place(Model, table="places"):
    id: Column[int] = column(datatype.INTEGER, primary_key=True)
    geom: Column[BaseGeometry] = column(default=Point(0, 0))
    area: Column[BaseGeometry | None] = column(datatype.GEOMETRY("OGC:CRS84"), default=None)


def test_geometry_column_round_trip(con: duckdb.DuckDBPyConnection) -> None:
    q = create_table(Place)
    assert '"geom" GEOMETRY NOT NULL DEFAULT ' in q.sql
    assert "\"area\" GEOMETRY('OGC:CRS84')" in q.sql
    q.execute(con)

    insert(Place, ["id", "geom", "area"]).values((1, point, square)).execute(con)
    insert(Place, ["id"]).values((2,)).execute(con)

    rows = select(Place.id, Place.geom, Place.area).from_(Place).order_by(Place.id).execute(con).fetchall()
    assert [(i, shapely.from_wkb(g), a and shapely.from_wkb(a)) for i, g, a in rows] == [
        (1, point, square),
        (2, Point(0, 0), None),
    ]
    assert select(col("id")).from_(Place).where(Place.geom == point).execute(con).fetchall() == [(1,)]
