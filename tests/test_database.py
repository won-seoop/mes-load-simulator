"""EXP-011 regression test: the sqlite3 driver connection must use a longer
busy-wait than its 5s default, not the sqlite3 driver's bare default.

See app/database.py for the full story (PAR-014's `database is locked`
500s, and why WAL mode was tried and rejected) and
experiments/EXP-011-sqlite-write-lock for the before/after load-test numbers.
"""

from app.database import engine


def test_sqlite_busy_timeout_raised_above_driver_default():
    assert engine.url.get_backend_name() == "sqlite"
    conn = engine.raw_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA busy_timeout")
        # sqlite3's own driver default is 5000ms; app/database.py raises it
        # to 15000ms (connect_args={"timeout": 15}).
        assert cursor.fetchone()[0] == 15000
    finally:
        conn.close()
