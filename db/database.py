import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "attendance.db")


def init_db():
    """Initialize database with schema."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        schema = f.read()
    with get_conn() as conn:
        conn.executescript(schema)
    print(f"[DB] Initialized at {DB_PATH}")


@contextmanager
def get_conn():
    """Yield a sqlite3 connection with row_factory set."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Students ──────────────────────────────────────────────────────────────────

def register_student(telegram_id: int, telegram_username: str, student_id: str, full_name: str) -> bool:
    """Returns True if newly registered, False if already exists."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM students WHERE telegram_id = ? OR student_id = ?",
            (telegram_id, student_id)
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO students (telegram_id, telegram_username, student_id, full_name) VALUES (?, ?, ?, ?)",
            (telegram_id, telegram_username, student_id, full_name)
        )
        return True


def get_student_by_telegram(telegram_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM students WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()


# ── Sessions ──────────────────────────────────────────────────────────────────

def create_session(session_id: str, course_name: str, professor_name: str,
                   lat: float, lng: float, radius_meters: int, expires_at: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sessions (id, course_name, professor_name, lat, lng, radius_meters, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session_id, course_name, professor_name, lat, lng, radius_meters, expires_at)
        )


def get_session(session_id: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()


def deactivate_session(session_id: str):
    with get_conn() as conn:
        conn.execute("UPDATE sessions SET is_active = 0 WHERE id = ?", (session_id,))


# ── Attendance ─────────────────────────────────────────────────────────────────

def record_attendance(session_id: str, student_id: str, telegram_id: int,
                      lat: float, lng: float, distance: float) -> bool:
    """Returns True on success, False if duplicate."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM attendance WHERE session_id = ? AND student_id = ?",
            (session_id, student_id)
        ).fetchone()
        if existing:
            return False
        conn.execute(
            """INSERT INTO attendance (session_id, student_id, telegram_id, submitted_lat, submitted_lng, distance_meters)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, student_id, telegram_id, lat, lng, distance)
        )
        return True


def get_attendance_for_session(session_id: str):
    with get_conn() as conn:
        return conn.execute(
            """SELECT a.submitted_at, a.distance_meters, s.student_id, s.full_name, s.telegram_username
               FROM attendance a
               JOIN students s ON a.student_id = s.student_id
               WHERE a.session_id = ?
               ORDER BY a.submitted_at ASC""",
            (session_id,)
        ).fetchall()
