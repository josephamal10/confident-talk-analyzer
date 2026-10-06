"""One database interface over SQLite (local use, tests) and Postgres (the deployed app).

Set DATABASE_URL (postgresql://...) to use Postgres; otherwise the SQLite file at DATABASE_PATH is used.
The app writes SQLite-style SQL with `?` placeholders; for Postgres they become `%s`, the schema's
SQLite types are mapped, and rows can be read by column name or position either way.
"""
import os
import sqlite3
import threading

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_PATH = os.getenv("DATABASE_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_data.db")
POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))

try:
    import psycopg
except ImportError:  # only needed when DATABASE_URL points at Postgres
    psycopg = None

IntegrityError = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())

_pool = None
_pool_lock = threading.Lock()


class Row(dict):
    """A Postgres row that, like sqlite3.Row, can be indexed by column name or position."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    names = [column.name for column in cursor.description or []]
    return lambda values: Row(zip(names, values))


def _postgres_sql(sql):
    return sql.replace("%", "%%").replace("?", "%s")


def postgres_schema(schema):
    return (schema.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
            .replace(" REAL", " DOUBLE PRECISION"))


def _get_pool():
    global _pool
    with _pool_lock:
        if _pool is None:
            from psycopg_pool import ConnectionPool

            # Hosted Postgres (Neon) closes idle connections, so each one is checked before use.
            _pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=5, check=ConnectionPool.check_connection,
                                   kwargs={"row_factory": _row_factory}, open=True)
    return _pool


class Connection:
    """The subset of sqlite3.Connection the app uses, for either database."""

    def __init__(self):
        if POSTGRES:
            self._pool = _get_pool()
            self._conn = self._pool.getconn()
        else:
            self._pool = None
            self._conn = sqlite3.connect(SQLITE_PATH, timeout=10)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")

    def execute(self, sql, params=()):
        if not POSTGRES:
            return self._conn.execute(sql, params)
        try:
            return self._conn.execute(_postgres_sql(sql), params)
        except Exception:
            # Postgres refuses every later statement in a failed transaction until it is rolled back.
            self._conn.rollback()
            raise

    def insert(self, sql, params=()):
        """Runs an INSERT and returns the new row's id."""
        if not POSTGRES:
            return self._conn.execute(sql, params).lastrowid
        return self.execute(sql + " RETURNING id", params).fetchone()[0]

    def commit(self):
        self._conn.commit()

    def close(self):
        if self._pool is not None:
            if self._conn.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                self._conn.rollback()  # reads leave a transaction open; end it before reuse
            self._pool.putconn(self._conn)
        else:
            self._conn.close()


def connect():
    return Connection()


def init(schema, added_columns):
    """Creates the tables, and adds columns introduced after the first release to older databases."""
    db = connect()
    try:
        if POSTGRES:
            db._conn.execute(postgres_schema(schema))
            for table, columns in added_columns.items():
                for column, column_type in columns.items():
                    db._conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {column_type}")
        else:
            db._conn.executescript(schema)
            for table, columns in added_columns.items():
                existing = {row[1] for row in db._conn.execute(f"PRAGMA table_info({table})")}
                for column, column_type in columns.items():
                    if column not in existing:
                        db._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")
        db.commit()
    finally:
        db.close()
