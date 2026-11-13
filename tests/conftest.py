from collections.abc import Iterator

import duckdb
import pytest


@pytest.fixture
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    conn = duckdb.connect()
    conn.execute(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, name VARCHAR, age INTEGER, dept VARCHAR);
        INSERT INTO users VALUES
            (1, 'alice', 30, 'eng'),
            (2, 'bob', 25, 'eng'),
            (3, 'carol', 41, 'sales'),
            (4, 'dave', NULL, 'sales'),
            (5, 'eve', 35, NULL);
        CREATE TABLE orders (id INTEGER, user_id INTEGER, amount DECIMAL(10, 2), ts TIMESTAMP);
        INSERT INTO orders VALUES
            (10, 1, 100.00, '2026-01-01 10:00'),
            (11, 1, 50.50, '2026-01-02 11:00'),
            (12, 2, 20.00, '2026-01-03 12:00'),
            (13, 3, 999.99, '2026-01-04 13:00');
        """,
    )
    yield conn
    conn.close()
