import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "bitacora.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    has_lifetime_access INTEGER NOT NULL DEFAULT 0,
    capital_inicial REAL NOT NULL DEFAULT 1000,
    riesgo_pct REAL NOT NULL DEFAULT 0.02,
    rr REAL NOT NULL DEFAULT 2,
    be_trigger REAL NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    op_date TEXT,
    session TEXT NOT NULL,
    direction TEXT,
    r_points REAL,
    result TEXT NOT NULL,
    recorrido TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS stripe_events (
    event_id TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_operations_user ON operations(user_id);
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)


def get_user_by_email(email):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def create_user(email, password_hash):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email.lower().strip(), password_hash),
        )
        return cur.lastrowid


def grant_lifetime_access(user_id):
    with get_db() as conn:
        conn.execute("UPDATE users SET has_lifetime_access = 1 WHERE id = ?", (user_id,))


def update_settings(user_id, capital_inicial, riesgo_pct, rr, be_trigger):
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET capital_inicial=?, riesgo_pct=?, rr=?, be_trigger=? WHERE id=?",
            (capital_inicial, riesgo_pct, rr, be_trigger, user_id),
        )


def list_operations(user_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM operations WHERE user_id=? ORDER BY id ASC", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def add_operation(user_id, op_date, session, direction, r_points, result, recorrido):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO operations (user_id, op_date, session, direction, r_points, result, recorrido)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, op_date, session, direction, r_points, result, recorrido),
        )


def delete_operation(user_id, op_id):
    with get_db() as conn:
        conn.execute("DELETE FROM operations WHERE id=? AND user_id=?", (op_id, user_id))


def event_already_processed(event_id):
    with get_db() as conn:
        row = conn.execute("SELECT 1 FROM stripe_events WHERE event_id=?", (event_id,)).fetchone()
        return row is not None


def mark_event_processed(event_id):
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO stripe_events (event_id) VALUES (?)", (event_id,)
        )
