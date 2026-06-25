import sqlite3
import time
from pathlib import Path

DB_FILE = Path(__file__).with_name("memory.db")
LEGACY_SESSION_TITLE = "Legacy history"
TASK_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _connect():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT    NOT NULL,
                created_at REAL    NOT NULL,
                updated_at REAL    NOT NULL
            );
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
            CREATE TABLE IF NOT EXISTS task_runs (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                title            TEXT    NOT NULL,
                prompt           TEXT    NOT NULL,
                status           TEXT    NOT NULL DEFAULT 'queued',
                final_result     TEXT,
                error            TEXT,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                worker_id        TEXT,
                created_at       REAL    NOT NULL,
                updated_at       REAL    NOT NULL,
                started_at       REAL,
                completed_at     REAL
            );
            CREATE TABLE IF NOT EXISTS task_events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id    INTEGER NOT NULL,
                event_type TEXT    NOT NULL,
                message    TEXT    NOT NULL,
                payload    TEXT,
                timestamp  REAL    NOT NULL,
                FOREIGN KEY(task_id) REFERENCES task_runs(id)
            );
            CREATE TABLE IF NOT EXISTS worker_heartbeats (
                worker_id       TEXT PRIMARY KEY,
                status          TEXT NOT NULL,
                current_task_id INTEGER,
                last_seen       REAL NOT NULL,
                started_at      REAL NOT NULL,
                info            TEXT
            );
        """)
        # Migration: older DBs have a reflections table without `active`.
        reflection_cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(reflections)")
        }
        if "active" not in reflection_cols:
            conn.execute(
                "ALTER TABLE reflections ADD COLUMN active INTEGER NOT NULL DEFAULT 1"
            )
        # Migration: attach existing flat messages to one session without changing ids.
        message_cols = {
            r["name"] for r in conn.execute("PRAGMA table_info(messages)")
        }
        if "session_id" not in message_cols:
            conn.execute("ALTER TABLE messages ADD COLUMN session_id INTEGER")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_session_id "
            "ON messages(session_id, id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at "
            "ON chat_sessions(updated_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_runs_status_updated "
            "ON task_runs(status, updated_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_events_task_id "
            "ON task_events(task_id, id)"
        )

        pending = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id IS NULL"
        ).fetchone()[0]
        if pending:
            legacy_id = _ensure_legacy_session(conn)
            conn.execute(
                "UPDATE messages SET session_id = ? WHERE session_id IS NULL",
                (legacy_id,),
            )


def _ensure_legacy_session(conn) -> int:
    row = conn.execute(
        "SELECT id FROM chat_sessions WHERE title = ? ORDER BY id LIMIT 1",
        (LEGACY_SESSION_TITLE,),
    ).fetchone()
    if row:
        return row["id"]

    stats = conn.execute(
        "SELECT MIN(timestamp), MAX(timestamp) FROM messages"
    ).fetchone()
    now = time.time()
    created_at = stats[0] if stats and stats[0] is not None else now
    updated_at = stats[1] if stats and stats[1] is not None else now
    cur = conn.execute(
        "INSERT INTO chat_sessions (title, created_at, updated_at) "
        "VALUES (?, ?, ?)",
        (LEGACY_SESSION_TITLE, created_at, updated_at),
    )
    return cur.lastrowid


def insert_message(
    role: str,
    content: str,
    timestamp: float,
    session_id: int | None = None,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO messages (role, content, timestamp, session_id) "
            "VALUES (?, ?, ?, ?)",
            (role, content, timestamp, session_id),
        )
        if session_id is not None:
            conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
                (timestamp, session_id),
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


def get_messages_for_session_context(session_id: int, n: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages "
            "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, n * 2),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def create_session(title: str = "New chat") -> dict:
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO chat_sessions (title, created_at, updated_at) "
            "VALUES (?, ?, ?)",
            (title, now, now),
        )
        row = conn.execute(
            "SELECT id, title, created_at, updated_at FROM chat_sessions "
            "WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return dict(row)


def get_session(session_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, title, created_at, updated_at FROM chat_sessions "
            "WHERE id = ?",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def list_sessions() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("""
            SELECT
                s.id,
                s.title,
                s.created_at,
                s.updated_at,
                COUNT(m.id) AS message_count,
                (
                    SELECT m2.content
                    FROM messages m2
                    WHERE m2.session_id = s.id
                    ORDER BY m2.id DESC
                    LIMIT 1
                ) AS last_message
            FROM chat_sessions s
            LEFT JOIN messages m ON m.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC, s.id DESC
        """).fetchall()
    return [dict(r) for r in rows]


def get_session_messages(session_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, role, content, timestamp FROM messages "
            "WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_session_title(session_id: int, title: str) -> dict | None:
    with _connect() as conn:
        now = time.time()
        conn.execute(
            "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, session_id),
        )
        row = conn.execute(
            "SELECT id, title, created_at, updated_at FROM chat_sessions "
            "WHERE id = ?",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def count_messages() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


def count_sessions() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0]


def count_active_reflections() -> int:
    with _connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM reflections WHERE active = 1"
        ).fetchone()[0]


def _row_to_dict(row) -> dict | None:
    return dict(row) if row else None


def _task_row(row) -> dict | None:
    if row is None:
        return None
    task = dict(row)
    task["cancel_requested"] = bool(task["cancel_requested"])
    return task


def create_task_run(prompt: str, title: str | None = None) -> dict:
    now = time.time()
    normalized_prompt = prompt.strip()
    normalized_title = title or normalized_prompt[:64].strip() or "Background task"
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO task_runs "
            "(title, prompt, status, created_at, updated_at) "
            "VALUES (?, ?, 'queued', ?, ?)",
            (normalized_title, normalized_prompt, now, now),
        )
        row = conn.execute(
            "SELECT * FROM task_runs WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return _task_row(row)


def list_task_runs(limit: int = 50) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM task_runs ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_task_row(r) for r in rows]


def list_active_task_runs(limit: int = 10) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM task_runs "
            "WHERE status NOT IN ('completed', 'failed', 'cancelled') "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_task_row(r) for r in rows]


def get_task_run(task_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM task_runs WHERE id = ?", (task_id,)).fetchone()
    return _task_row(row)


def add_task_event(
    task_id: int,
    event_type: str,
    message: str,
    payload: str | None = None,
) -> dict:
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO task_events (task_id, event_type, message, payload, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (task_id, event_type, message, payload, now),
        )
        conn.execute(
            "UPDATE task_runs SET updated_at = ? WHERE id = ?",
            (now, task_id),
        )
        row = conn.execute(
            "SELECT * FROM task_events WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return dict(row)


def list_task_events(task_id: int) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM task_events WHERE task_id = ? ORDER BY id",
            (task_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def claim_next_task(worker_id: str) -> dict | None:
    now = time.time()
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM task_runs WHERE status = 'queued' "
            "ORDER BY created_at ASC, id ASC LIMIT 1"
        ).fetchone()
        if row is None:
            conn.commit()
            return None

        conn.execute(
            "UPDATE task_runs SET status = 'running', worker_id = ?, "
            "started_at = ?, updated_at = ? WHERE id = ?",
            (worker_id, now, now, row["id"]),
        )
        updated = conn.execute(
            "SELECT * FROM task_runs WHERE id = ?",
            (row["id"],),
        ).fetchone()
        conn.commit()
    return _task_row(updated)


def set_task_completed(task_id: int, final_result: str):
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "UPDATE task_runs SET status = 'completed', final_result = ?, "
            "error = NULL, completed_at = ?, updated_at = ? WHERE id = ?",
            (final_result, now, now, task_id),
        )


def set_task_failed(task_id: int, error: str):
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "UPDATE task_runs SET status = 'failed', error = ?, "
            "completed_at = ?, updated_at = ? WHERE id = ?",
            (error, now, now, task_id),
        )


def set_task_cancelled(task_id: int, reason: str = "Cancelled"):
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "UPDATE task_runs SET status = 'cancelled', error = ?, "
            "completed_at = ?, updated_at = ? WHERE id = ?",
            (reason, now, now, task_id),
        )


def request_task_cancel(task_id: int) -> dict | None:
    now = time.time()
    with _connect() as conn:
        task = conn.execute(
            "SELECT * FROM task_runs WHERE id = ?",
            (task_id,),
        ).fetchone()
        if task is None:
            return None
        if task["status"] == "queued":
            conn.execute(
                "UPDATE task_runs SET status = 'cancelled', cancel_requested = 1, "
                "completed_at = ?, updated_at = ? WHERE id = ?",
                (now, now, task_id),
            )
        elif task["status"] not in TASK_TERMINAL_STATUSES:
            conn.execute(
                "UPDATE task_runs SET cancel_requested = 1, updated_at = ? WHERE id = ?",
                (now, task_id),
            )
        row = conn.execute(
            "SELECT * FROM task_runs WHERE id = ?",
            (task_id,),
        ).fetchone()
    return _task_row(row)


def task_cancel_requested(task_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT cancel_requested, status FROM task_runs WHERE id = ?",
            (task_id,),
        ).fetchone()
    return bool(row and (row["cancel_requested"] or row["status"] == "cancelled"))


def update_worker_heartbeat(
    worker_id: str,
    status: str,
    current_task_id: int | None = None,
    info: str | None = None,
):
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO worker_heartbeats "
            "(worker_id, status, current_task_id, last_seen, started_at, info) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(worker_id) DO UPDATE SET "
            "status = excluded.status, "
            "current_task_id = excluded.current_task_id, "
            "last_seen = excluded.last_seen, "
            "info = excluded.info",
            (worker_id, status, current_task_id, now, now, info),
        )


def list_worker_heartbeats() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM worker_heartbeats ORDER BY last_seen DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_latest_worker_heartbeat() -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM worker_heartbeats ORDER BY last_seen DESC LIMIT 1"
        ).fetchone()
    return _row_to_dict(row)


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
