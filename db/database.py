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
        # Migration: add group_name column if upgrading from older version
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN group_name TEXT NOT NULL DEFAULT ''")
            print("[DB] Migrated: added group_name column")
        except Exception:
            pass  # Column already exists
        # Migration: add method/note columns if upgrading from older version
        for col, definition in [("method", "TEXT DEFAULT 'qr'"), ("note", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE attendance ADD COLUMN {col} {definition}")
                print(f"[DB] Migrated: added {col} column")
            except Exception:
                pass
        # Migration: add total_enrolled column if upgrading
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN total_enrolled INTEGER DEFAULT 0")
            print("[DB] Migrated: added total_enrolled column")
        except Exception:
            pass
        # Migration: create groups table if not exists
        conn.execute("""CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            enrollment INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        # Migration: add group_id to students if not exists
        try:
            conn.execute("ALTER TABLE students ADD COLUMN group_id INTEGER REFERENCES groups(id)")
            print("[DB] Migrated: added group_id to students")
        except Exception:
            pass
        # Migration: create professors table if not exists
        conn.execute("""CREATE TABLE IF NOT EXISTS professors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        # Migration: add professor_id to sessions if not exists
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN professor_id INTEGER REFERENCES professors(id)")
            print("[DB] Migrated: added professor_id to sessions")
        except Exception:
            pass
        # Migration: create locations table if not exists
        conn.execute("""CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            radius_meters INTEGER NOT NULL DEFAULT 100,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
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

def create_session(session_id: str, course_name: str, group_name: str, professor_name: str,
                   lat: float, lng: float, radius_meters: int, expires_at: str,
                   total_enrolled: int = 0):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sessions (id, course_name, group_name, professor_name, lat, lng,
               radius_meters, expires_at, total_enrolled)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, course_name, group_name, professor_name, lat, lng,
             radius_meters, expires_at, total_enrolled)
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
            """INSERT INTO attendance (session_id, student_id, telegram_id, submitted_lat, submitted_lng, distance_meters, method)
               VALUES (?, ?, ?, ?, ?, ?, 'qr')""",
            (session_id, student_id, telegram_id, lat, lng, distance)
        )
        return True


def record_manual_attendance(session_id: str, student_id: str, note: str = "") -> tuple[bool, str]:
    """
    Manually mark a student present.
    Returns (success, reason). Reason is set if failed.
    """
    with get_conn() as conn:
        student = conn.execute(
            "SELECT student_id, full_name FROM students WHERE student_id = ?", (student_id,)
        ).fetchone()
        if not student:
            return False, "Student ID not found in the system."

        existing = conn.execute(
            "SELECT id, method FROM attendance WHERE session_id = ? AND student_id = ?",
            (session_id, student_id)
        ).fetchone()
        if existing:
            return False, f"Already marked present via {existing['method']}."

        conn.execute(
            """INSERT INTO attendance (session_id, student_id, telegram_id, submitted_lat, submitted_lng,
               distance_meters, method, note)
               VALUES (?, ?, NULL, NULL, NULL, NULL, 'manual', ?)""",
            (session_id, student_id, note)
        )
        return True, student["full_name"]


def search_students(query: str):
    """Search students by name or student_id for manual override autocomplete."""
    with get_conn() as conn:
        like = f"%{query}%"
        return conn.execute(
            """SELECT student_id, full_name, telegram_username FROM students
               WHERE student_id LIKE ? OR full_name LIKE ?
               LIMIT 10""",
            (like, like)
        ).fetchall()


def get_attendance_for_session(session_id: str):
    with get_conn() as conn:
        return conn.execute(
            """SELECT a.submitted_at, a.distance_meters, a.method, a.note,
                      s.student_id, s.full_name, s.telegram_username
               FROM attendance a
               JOIN students s ON a.student_id = s.student_id
               WHERE a.session_id = ?
               ORDER BY a.submitted_at ASC""",
            (session_id,)
        ).fetchall()


def get_all_sessions(professor_id: int = None):
    """Return sessions. If professor_id given, only return that professor's sessions."""
    with get_conn() as conn:
        if professor_id:
            return conn.execute(
                """SELECT s.id, s.course_name, s.group_name, s.professor_name, s.created_at, s.expires_at, s.is_active,
                          COUNT(a.id) as attendance_count
                   FROM sessions s
                   LEFT JOIN attendance a ON s.id = a.session_id
                   WHERE s.professor_id = ?
                   GROUP BY s.id
                   ORDER BY s.created_at DESC""",
                (professor_id,)
            ).fetchall()
        return conn.execute(
            """SELECT s.id, s.course_name, s.group_name, s.professor_name, s.created_at, s.expires_at, s.is_active,
                      COUNT(a.id) as attendance_count
               FROM sessions s
               LEFT JOIN attendance a ON s.id = a.session_id
               GROUP BY s.id
               ORDER BY s.created_at DESC""",
        ).fetchall()


# ── Student Stats ──────────────────────────────────────────────────────────────

def get_student_stats(student_id: str):
    """
    Returns per-course attendance stats for a student.
    Each row: course_name, total_sessions, attended, percentage
    """
    with get_conn() as conn:
        return conn.execute(
            """SELECT
                s.course_name,
                s.group_name,
                COUNT(DISTINCT s.id) as total_sessions,
                COUNT(DISTINCT a.session_id) as attended,
                ROUND(COUNT(DISTINCT a.session_id) * 100.0 / COUNT(DISTINCT s.id), 1) as percentage
               FROM sessions s
               LEFT JOIN attendance a ON s.id = a.session_id AND a.student_id = ?
               GROUP BY s.course_name, s.group_name
               ORDER BY s.course_name ASC, s.group_name ASC""",
            (student_id,)
        ).fetchall()


def get_course_student_summary(course_name: str, group_name: str = "", professor_id: int = None):
    """
    Returns ALL students in the group with their attendance %.
    Students who never attended show 0% — not hidden.
    Filters sessions by professor_id if provided.
    """
    with get_conn() as conn:
        # Build session filter
        if professor_id:
            session_filter = "AND s.professor_id = ?"
            params_total = (course_name, group_name, professor_id)
        else:
            session_filter = ""
            params_total = (course_name, group_name)

        # Total sessions for this course+group (by this professor)
        total_sessions_row = conn.execute(
            f"SELECT COUNT(DISTINCT id) as cnt FROM sessions s WHERE s.course_name = ? AND s.group_name = ? {session_filter}",
            params_total
        ).fetchone()
        total_sessions = total_sessions_row["cnt"] if total_sessions_row else 0

        if total_sessions == 0:
            return []

        # Get group_id for this group name to find all enrolled students
        group_row = conn.execute(
            "SELECT id FROM groups WHERE name = ?", (group_name,)
        ).fetchone()

        if group_row:
            # Use group membership — includes students with 0 attendance
            group_id = group_row["id"]
            if professor_id:
                params = (total_sessions, total_sessions, course_name, group_name, professor_id, group_id)
                session_join = "AND s.professor_id = ?"
            else:
                params = (total_sessions, total_sessions, course_name, group_name, group_id)
                session_join = ""

            return conn.execute(
                f"""SELECT
                    st.student_id,
                    st.full_name,
                    st.telegram_username,
                    ? as total_sessions,
                    COUNT(DISTINCT a.session_id) as attended,
                    ROUND(COUNT(DISTINCT a.session_id) * 100.0 / ?, 1) as percentage
                   FROM students st
                   LEFT JOIN attendance a ON a.student_id = st.student_id
                   LEFT JOIN sessions s ON s.id = a.session_id
                       AND s.course_name = ? AND s.group_name = ? {session_join}
                   WHERE st.group_id = ?
                   GROUP BY st.student_id
                   ORDER BY percentage ASC, st.full_name ASC""",
                params
            ).fetchall()
        else:
            # Fallback: no group membership — show only students who attended
            if professor_id:
                params2 = (total_sessions, total_sessions, course_name, group_name, professor_id)
                session_join2 = "AND s.professor_id = ?"
            else:
                params2 = (total_sessions, total_sessions, course_name, group_name)
                session_join2 = ""

            return conn.execute(
                f"""SELECT
                    st.student_id,
                    st.full_name,
                    st.telegram_username,
                    ? as total_sessions,
                    COUNT(DISTINCT a.session_id) as attended,
                    ROUND(COUNT(DISTINCT a.session_id) * 100.0 / ?, 1) as percentage
                   FROM students st
                   INNER JOIN attendance a ON a.student_id = st.student_id
                   INNER JOIN sessions s ON s.id = a.session_id
                       AND s.course_name = ? AND s.group_name = ? {session_join2}
                   GROUP BY st.student_id
                   ORDER BY percentage ASC""",
                params2
            ).fetchall()


def get_all_courses(professor_id: int = None):
    """Returns distinct course + group combinations, optionally filtered by professor."""
    with get_conn() as conn:
        if professor_id:
            return conn.execute(
                """SELECT DISTINCT course_name, group_name
                   FROM sessions
                   WHERE professor_id = ?
                   ORDER BY course_name ASC, group_name ASC""",
                (professor_id,)
            ).fetchall()
        return conn.execute(
            """SELECT DISTINCT course_name, group_name
               FROM sessions
               ORDER BY course_name ASC, group_name ASC"""
        ).fetchall()


# ── Saved Locations ────────────────────────────────────────────────────────────

def save_location(name: str, lat: float, lng: float, radius: int) -> bool:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM locations WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE locations SET lat=?, lng=?, radius_meters=? WHERE name=?",
                (lat, lng, radius, name)
            )
        else:
            conn.execute(
                "INSERT INTO locations (name, lat, lng, radius_meters) VALUES (?, ?, ?, ?)",
                (name, lat, lng, radius)
            )
        return True


def get_locations():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM locations ORDER BY name ASC"
        ).fetchall()


def delete_location(name: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM locations WHERE name = ?", (name,))


# ── Admin Statistics ───────────────────────────────────────────────────────────

def get_professor_stats(since_date: str = None):
    """
    Returns attendance rate per professor.
    since_date: ISO date string e.g. '2024-01-01', or None for all time.
    """
    with get_conn() as conn:
        date_filter = "AND s.created_at >= ?" if since_date else ""
        params = (since_date,) if since_date else ()
        return conn.execute(
            f"""SELECT
                s.professor_name,
                COUNT(DISTINCT s.id) as total_sessions,
                COUNT(DISTINCT s.course_name || s.group_name) as total_groups,
                COALESCE(SUM(a.student_count), 0) as total_attendances,
                ROUND(AVG(a.student_count * 1.0), 1) as avg_per_session
               FROM sessions s
               LEFT JOIN (
                   SELECT session_id, COUNT(*) as student_count
                   FROM attendance GROUP BY session_id
               ) a ON a.session_id = s.id
               WHERE 1=1 {date_filter}
               GROUP BY s.professor_name
               ORDER BY avg_per_session DESC""",
            params
        ).fetchall()


def get_group_stats(since_date: str = None):
    """
    Returns attendance rate per class/group (aggregated across all subjects).
    """
    with get_conn() as conn:
        date_filter = "AND s.created_at >= ?" if since_date else ""
        params = (since_date,) if since_date else ()
        return conn.execute(
            f"""SELECT
                s.group_name,
                COUNT(DISTINCT s.id) as total_sessions,
                COUNT(DISTINCT s.course_name) as total_subjects,
                COALESCE(SUM(a.student_count), 0) as total_attendances,
                ROUND(AVG(a.student_count * 1.0), 1) as avg_per_session,
                CASE
                    WHEN SUM(CASE WHEN s.total_enrolled > 0 THEN 1 ELSE 0 END) > 0
                    THEN ROUND(
                        SUM(CASE WHEN s.total_enrolled > 0 AND a.student_count IS NOT NULL
                            THEN a.student_count * 100.0 / s.total_enrolled ELSE 0 END)
                        / NULLIF(SUM(CASE WHEN s.total_enrolled > 0 THEN 1 ELSE 0 END), 0)
                    , 1)
                    ELSE NULL
                END as avg_rate,
                SUM(CASE WHEN s.total_enrolled > 0 THEN 1 ELSE 0 END) as enrolled_session_count
               FROM sessions s
               LEFT JOIN (
                   SELECT session_id, COUNT(*) as student_count
                   FROM attendance GROUP BY session_id
               ) a ON a.session_id = s.id
               WHERE 1=1 {date_filter}
               GROUP BY s.group_name
               ORDER BY COALESCE(avg_rate, avg_per_session) DESC""",
            params
        ).fetchall()


def get_subject_stats(since_date: str = None):
    """
    Returns attendance rate per subject (aggregated across all groups).
    """
    with get_conn() as conn:
        date_filter = "AND s.created_at >= ?" if since_date else ""
        params = (since_date,) if since_date else ()
        return conn.execute(
            f"""SELECT
                s.course_name,
                COUNT(DISTINCT s.id) as total_sessions,
                COUNT(DISTINCT s.group_name) as total_groups,
                COALESCE(SUM(a.student_count), 0) as total_attendances,
                ROUND(AVG(a.student_count * 1.0), 1) as avg_per_session,
                CASE
                    WHEN SUM(CASE WHEN s.total_enrolled > 0 THEN 1 ELSE 0 END) > 0
                    THEN ROUND(
                        SUM(CASE WHEN s.total_enrolled > 0 AND a.student_count IS NOT NULL
                            THEN a.student_count * 100.0 / s.total_enrolled ELSE 0 END)
                        / NULLIF(SUM(CASE WHEN s.total_enrolled > 0 THEN 1 ELSE 0 END), 0)
                    , 1)
                    ELSE NULL
                END as avg_rate,
                SUM(CASE WHEN s.total_enrolled > 0 THEN 1 ELSE 0 END) as enrolled_session_count
               FROM sessions s
               LEFT JOIN (
                   SELECT session_id, COUNT(*) as student_count
                   FROM attendance GROUP BY session_id
               ) a ON a.session_id = s.id
               WHERE 1=1 {date_filter}
               GROUP BY s.course_name
               ORDER BY COALESCE(avg_rate, avg_per_session) DESC""",
            params
        ).fetchall()


def get_matrix_stats(since_date: str = None):
    """
    Returns attendance rate for every group x subject combination.
    """
    with get_conn() as conn:
        date_filter = "AND s.created_at >= ?" if since_date else ""
        params = (since_date,) if since_date else ()
        return conn.execute(
            f"""SELECT
                s.group_name,
                s.course_name,
                COUNT(DISTINCT s.id) as total_sessions,
                COALESCE(SUM(a.student_count), 0) as total_attendances,
                ROUND(AVG(a.student_count * 1.0), 1) as avg_per_session,
                ROUND(AVG(
                    CASE WHEN s.total_enrolled > 0
                    THEN a.student_count * 100.0 / s.total_enrolled
                    ELSE NULL END
                ), 1) as avg_rate,
                MAX(s.total_enrolled) as enrolled
               FROM sessions s
               LEFT JOIN (
                   SELECT session_id, COUNT(*) as student_count
                   FROM attendance GROUP BY session_id
               ) a ON a.session_id = s.id
               WHERE 1=1 {date_filter}
               GROUP BY s.group_name, s.course_name
               ORDER BY s.group_name ASC, s.course_name ASC""",
            params
        ).fetchall()


def get_admin_overview(since_date: str = None):
    """Top-level numbers for admin dashboard."""
    with get_conn() as conn:
        date_filter = "WHERE created_at >= ?" if since_date else ""
        params = (since_date,) if since_date else ()
        sessions = conn.execute(
            f"SELECT COUNT(*) as cnt FROM sessions {date_filter}", params
        ).fetchone()["cnt"]

        att_filter = f"""WHERE session_id IN (
            SELECT id FROM sessions {'WHERE created_at >= ?' if since_date else ''}
        )"""
        attendances = conn.execute(
            f"SELECT COUNT(*) as cnt FROM attendance {att_filter}", params
        ).fetchone()["cnt"]

        students = conn.execute(
            "SELECT COUNT(*) as cnt FROM students"
        ).fetchone()["cnt"]

        professors = conn.execute(
            f"SELECT COUNT(DISTINCT professor_name) as cnt FROM sessions {date_filter}", params
        ).fetchone()["cnt"]

        return {
            "total_sessions": sessions,
            "total_attendances": attendances,
            "total_students": students,
            "total_professors": professors,
        }


# ── Professor Accounts ─────────────────────────────────────────────────────────
import hashlib

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_professor(username: str, password: str, full_name: str) -> tuple[bool, str]:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM professors WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            return False, "Username already exists."
        conn.execute(
            "INSERT INTO professors (username, password_hash, full_name) VALUES (?, ?, ?)",
            (username, _hash_password(password), full_name)
        )
        return True, "Professor created."

def get_all_professors():
    with get_conn() as conn:
        return conn.execute(
            "SELECT id, username, full_name, is_active, created_at FROM professors ORDER BY full_name ASC"
        ).fetchall()

def get_professor_by_username(username: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM professors WHERE username = ?", (username,)
        ).fetchone()

def get_professor_by_id(prof_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM professors WHERE id = ?", (prof_id,)
        ).fetchone()

def verify_professor(username: str, password: str):
    with get_conn() as conn:
        prof = conn.execute(
            "SELECT * FROM professors WHERE username = ? AND is_active = 1", (username,)
        ).fetchone()
        if not prof:
            return None
        if prof["password_hash"] == _hash_password(password):
            return prof
        return None

def update_professor(prof_id: int, full_name: str = None, password: str = None, is_active: int = None):
    with get_conn() as conn:
        if full_name is not None:
            conn.execute("UPDATE professors SET full_name = ? WHERE id = ?", (full_name, prof_id))
        if password is not None:
            conn.execute("UPDATE professors SET password_hash = ? WHERE id = ?", (_hash_password(password), prof_id))
        if is_active is not None:
            conn.execute("UPDATE professors SET is_active = ? WHERE id = ?", (is_active, prof_id))

def delete_professor(prof_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM professors WHERE id = ?", (prof_id,))

def get_sessions_by_professor(prof_id: int):
    """Get all sessions belonging to a specific professor account."""
    with get_conn() as conn:
        return conn.execute(
            """SELECT s.id, s.course_name, s.group_name, s.professor_name, s.created_at,
                      s.expires_at, s.is_active, COUNT(a.id) as attendance_count
               FROM sessions s
               LEFT JOIN attendance a ON s.id = a.session_id
               WHERE s.professor_id = ?
               GROUP BY s.id
               ORDER BY s.created_at DESC""",
            (prof_id,)
        ).fetchall()


# ── Groups ─────────────────────────────────────────────────────────────────────

def create_group(name: str, enrollment: int) -> tuple[bool, str]:
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM groups WHERE name = ?", (name,)).fetchone()
        if existing:
            return False, "Group name already exists."
        conn.execute("INSERT INTO groups (name, enrollment) VALUES (?, ?)", (name, enrollment))
        return True, "Group created."

def get_all_groups():
    with get_conn() as conn:
        return conn.execute("""
            SELECT g.id, g.name, g.enrollment, g.created_at,
                   COUNT(s.id) as student_count
            FROM groups g
            LEFT JOIN students s ON s.group_id = g.id
            GROUP BY g.id ORDER BY g.name ASC
        """).fetchall()

def get_group_by_id(group_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()

def get_group_by_name(name: str):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM groups WHERE name = ?", (name,)).fetchone()

def update_group(group_id: int, name: str = None, enrollment: int = None):
    with get_conn() as conn:
        if name is not None:
            conn.execute("UPDATE groups SET name = ? WHERE id = ?", (name, group_id))
        if enrollment is not None:
            conn.execute("UPDATE groups SET enrollment = ? WHERE id = ?", (enrollment, group_id))

def delete_group(group_id: int):
    with get_conn() as conn:
        # Unlink students from this group first
        conn.execute("UPDATE students SET group_id = NULL WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))

def get_students_in_group(group_id: int):
    with get_conn() as conn:
        return conn.execute("""
            SELECT s.id, s.student_id, s.full_name, s.telegram_username, s.telegram_id
            FROM students s WHERE s.group_id = ?
            ORDER BY s.full_name ASC
        """, (group_id,)).fetchall()

def assign_student_group(telegram_id: int, group_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE students SET group_id = ? WHERE telegram_id = ?", (group_id, telegram_id))

def update_student(student_db_id: int, full_name: str = None, student_id: str = None):
    with get_conn() as conn:
        if full_name is not None:
            conn.execute("UPDATE students SET full_name = ? WHERE id = ?", (full_name, student_db_id))
        if student_id is not None:
            conn.execute("UPDATE students SET student_id = ? WHERE id = ?", (student_id, student_db_id))

def delete_student(student_db_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM students WHERE id = ?", (student_db_id,))
