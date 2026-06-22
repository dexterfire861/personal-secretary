import sqlite3
from pathlib import Path

DB_FILE = Path(__file__).with_name("memory.db")


def _connect():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                role            TEXT    NOT NULL,
                content         TEXT    NOT NULL,
                timestamp       REAL    NOT NULL,
                importance_score REAL
            );
            CREATE TABLE IF NOT EXISTS reflections (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                content   TEXT NOT NULL,
                timestamp REAL NOT NULL,
                active    INTEGER NOT NULL DEFAULT 1
            );
        """)
        # Migration: older DBs have a reflections table without `active`.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(reflections)")}
        if "active" not in cols:
            conn.execute(
                "ALTER TABLE reflections ADD COLUMN active INTEGER NOT NULL DEFAULT 1"
            )


def insert_message(role: str, content: str, timestamp: float) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO messages (role, content, timestamp) VALUES (?, ?, ?)",
            (role, content, timestamp),
        )
        return cur.lastrowid


def update_importance(msg_id: int, score: float):
    with _connect() as conn:
        conn.execute(
            "UPDATE messages SET importance_score = ? WHERE id = ?",
            (score, msg_id),
        )


def get_messages_for_context(n: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?",
            (n * 2,),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def get_messages_by_ids(ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id, role, content, timestamp, importance_score "
            f"FROM messages WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    return {r["id"]: dict(r) for r in rows}


def get_all_message_ids_and_content() -> list[tuple[int, str]]:
    with _connect() as conn:
        rows = conn.execute("SELECT id, content FROM messages ORDER BY id").fetchall()
    return [(r["id"], r["content"]) for r in rows]


def insert_reflection(content: str, timestamp: float) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO reflections (content, timestamp) VALUES (?, ?)",
            (content, timestamp),
        )
        return cur.lastrowid


def supersede_reflection(reflection_id: int):
    """Soft-delete: mark a reflection inactive instead of removing it,
    preserving the audit trail of how a fact evolved."""
    with _connect() as conn:
        conn.execute(
            "UPDATE reflections SET active = 0 WHERE id = ?",
            (reflection_id,),
        )


def get_active_reflections() -> list[dict]:
    """Active facts with ids, so the supersede logic can reference which
    existing fact a new one replaces."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, content FROM reflections WHERE active = 1 "
            "ORDER BY timestamp DESC LIMIT 10"
        ).fetchall()
    return [{"id": r["id"], "content": r["content"]} for r in rows]


def get_reflections() -> list[str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT content FROM reflections WHERE active = 1 "
            "ORDER BY timestamp DESC LIMIT 10"
        ).fetchall()
    return [r["content"] for r in rows]


def has_messages() -> bool:
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    return count > 0
