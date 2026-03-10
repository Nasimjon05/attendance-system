import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import base64
import io
import csv
from datetime import datetime, timedelta, timezone

import qrcode
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

import config
from db import database as db
from api.models import (
    CreateSessionRequest, SessionResponse,
    SessionAttendanceResponse, AttendanceRecord,
    ManualOverrideRequest, StudentSearchResult, SessionSummary
)

router = APIRouter()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _check_secret(secret: str):
    """Accept either the shared PROFESSOR_SECRET or any valid professor account password."""
    if secret == config.PROFESSOR_SECRET:
        return
    import hashlib
    hashed = hashlib.sha256(secret.encode()).hexdigest()
    with db.get_conn() as conn:
        prof = conn.execute(
            "SELECT id FROM professors WHERE password_hash = ? AND is_active = 1", (hashed,)
        ).fetchone()
    if not prof:
        raise HTTPException(status_code=403, detail="Invalid secret or server error.")


def _get_professor_id(secret: str) -> int | None:
    """Return professor_id if secret matches a professor account, else None (shared secret)."""
    if secret == config.PROFESSOR_SECRET:
        return None  # shared secret — no professor filter
    import hashlib
    hashed = hashlib.sha256(secret.encode()).hexdigest()
    with db.get_conn() as conn:
        prof = conn.execute(
            "SELECT id FROM professors WHERE password_hash = ? AND is_active = 1", (hashed,)
        ).fetchone()
    return prof["id"] if prof else None


def _check_admin_secret(secret: str):
    if secret != config.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid admin secret.")


@router.post("/auth/professor")
def auth_professor(secret: str = Query(...)):
    if secret != config.PROFESSOR_SECRET:
        raise HTTPException(status_code=403, detail="Invalid password.")
    return {"success": True, "role": "professor"}


@router.post("/auth/admin")
def auth_admin(secret: str = Query(...)):
    if secret != config.ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid password.")
    return {"success": True, "role": "admin"}


def _build_deep_link(session_id: str) -> str:
    return f"https://t.me/{config.BOT_USERNAME}?start={session_id}"


def _generate_qr_base64(data: str) -> str:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _format_records(records_raw) -> list[AttendanceRecord]:
    return [
        AttendanceRecord(
            student_id=r["student_id"],
            full_name=r["full_name"],
            telegram_username=r["telegram_username"],
            submitted_at=r["submitted_at"],
            distance_meters=round(r["distance_meters"], 1) if r["distance_meters"] else None,
            method=r["method"],
            note=r["note"],
        )
        for r in records_raw
    ]


# Create Session
@router.post("/sessions", response_model=SessionResponse)
def create_session(req: CreateSessionRequest):
    # Support both old shared secret and new professor account login
    prof = db.get_professor_by_username(req.secret) if hasattr(db, 'get_professor_by_username') else None
    if prof is None:
        _check_secret(req.secret)
    prof_id = prof["id"] if prof else None
    session_id = str(uuid.uuid4())
    now = _now_utc()
    expires_at = now + timedelta(seconds=req.validity_seconds)
    expires_str = expires_at.isoformat()
    # If using professor account, use their full_name as professor_name
    professor_name = req.professor_name
    if prof and not professor_name:
        professor_name = prof["full_name"]

    db.create_session(
        session_id=session_id,
        course_name=req.course_name,
        group_name=req.group_name,
        professor_name=professor_name,
        lat=req.lat,
        lng=req.lng,
        radius_meters=req.radius_meters,
        expires_at=expires_str,
        total_enrolled=req.total_enrolled,
    )
    # Link session to professor account if using account login
    if prof_id:
        import db.database as _db
        with _db.get_conn() as conn:
            conn.execute("UPDATE sessions SET professor_id = ? WHERE id = ?", (prof_id, session_id))
    deep_link = _build_deep_link(session_id)
    qr_b64 = _generate_qr_base64(deep_link)
    return SessionResponse(
        session_id=session_id,
        course_name=req.course_name,
        group_name=req.group_name,
        professor_name=req.professor_name,
        expires_at=expires_str,
        qr_deep_link=deep_link,
        qr_image_base64=qr_b64,
    )


# Get Attendance (live polling)
@router.get("/sessions/{session_id}/attendance", response_model=SessionAttendanceResponse)
def get_session_attendance(session_id: str, secret: str = Query(...)):
    _check_secret(secret)
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    records = _format_records(db.get_attendance_for_session(session_id))
    expires_at = datetime.fromisoformat(session["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    is_active = session["is_active"] == 1 and _now_utc() < expires_at
    return SessionAttendanceResponse(
        session_id=session_id,
        course_name=session["course_name"],
        group_name=session["group_name"] if "group_name" in session.keys() else "",
        professor_name=session["professor_name"],
        expires_at=session["expires_at"],
        is_active=is_active,
        total_count=len(records),
        records=records,
    )


# Manual Override
@router.post("/sessions/{session_id}/manual")
def manual_override(session_id: str, req: ManualOverrideRequest):
    _check_secret(req.secret)
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    success, result = db.record_manual_attendance(
        session_id=session_id,
        student_id=req.student_id,
        note=req.note,
    )
    if not success:
        raise HTTPException(status_code=400, detail=result)
    return {"success": True, "full_name": result, "student_id": req.student_id}


# Student Search
@router.get("/students/search", response_model=list[StudentSearchResult])
def search_students(q: str = Query(..., min_length=1), secret: str = Query(...)):
    _check_secret(secret)
    results = db.search_students(q)
    return [
        StudentSearchResult(
            student_id=r["student_id"],
            full_name=r["full_name"],
            telegram_username=r["telegram_username"],
        )
        for r in results
    ]


# Session History
@router.get("/sessions", response_model=list[SessionSummary])
def get_all_sessions(secret: str = Query(...)):
    _check_secret(secret)
    prof_id = _get_professor_id(secret)
    sessions = db.get_all_sessions(professor_id=prof_id)
    return [
        SessionSummary(
            session_id=s["id"],
            course_name=s["course_name"],
            group_name=s["group_name"],
            professor_name=s["professor_name"],
            created_at=s["created_at"],
            expires_at=s["expires_at"],
            is_active=s["is_active"] == 1,
            attendance_count=s["attendance_count"],
        )
        for s in sessions
    ]


# Export CSV
@router.get("/sessions/{session_id}/export/csv")
def export_csv(session_id: str, secret: str = Query(...)):
    _check_secret(secret)
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    records = db.get_attendance_for_session(session_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["#", "Student ID", "Full Name", "Telegram", "Method", "Distance (m)", "Time", "Note"])
    for i, r in enumerate(records, 1):
        writer.writerow([
            i,
            r["student_id"],
            r["full_name"],
            f"@{r['telegram_username']}" if r["telegram_username"] else "",
            r["method"].upper(),
            round(r["distance_meters"], 1) if r["distance_meters"] else "N/A",
            r["submitted_at"],
            r["note"] or "",
        ])
    output.seek(0)
    filename = f"attendance_{session['course_name'].replace(' ', '_')}_{session_id[:8]}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# Export PDF (opens browser print dialog)
@router.get("/sessions/{session_id}/export/pdf")
def export_pdf(session_id: str, secret: str = Query(...), sort: str = Query(default="time")):
    _check_secret(secret)
    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    records = list(db.get_attendance_for_session(session_id))
    if sort == "alpha":
        records = sorted(records, key=lambda r: r["full_name"].lower())
    rows = ""
    for i, r in enumerate(records, 1):
        method_badge = (
            '<span style="background:#d1fae5;color:#065f46;padding:2px 8px;border-radius:10px;font-size:11px;">QR</span>'
            if r["method"] == "qr" else
            '<span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:10px;font-size:11px;">MANUAL</span>'
        )
        note = r["note"] or ""
        distance = f"{round(r['distance_meters'], 1)}m" if r["distance_meters"] else "N/A"
        time_str = r["submitted_at"].split("T")[-1].split(".")[0] if "T" in str(r["submitted_at"]) else r["submitted_at"]
        rows += f"""<tr>
            <td>{i}</td><td>{r['student_id']}</td><td><strong>{r['full_name']}</strong></td>
            <td>{method_badge}</td><td>{distance}</td><td>{time_str}</td>
            <td style="color:#6b7280;font-size:11px;">{note}</td>
        </tr>"""
    date_str = str(session['created_at']).split('T')[0]
    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/>
<style>
  body{{font-family:Arial,sans-serif;padding:32px;color:#1a1a2e;}}
  h1{{font-size:20px;margin-bottom:4px;}}
  .meta{{color:#6b7280;font-size:13px;margin-bottom:24px;}}
  table{{width:100%;border-collapse:collapse;font-size:13px;}}
  th{{background:#1a1a2e;color:white;padding:8px 12px;text-align:left;}}
  td{{padding:8px 12px;border-bottom:1px solid #f0f2f5;}}
  .footer{{margin-top:24px;font-size:11px;color:#9ca3af;}}
  @media print{{body{{padding:0;}}}}
</style></head>
<body>
<h1>Attendance Sheet — {session['course_name']}</h1>
<div class="meta">Professor: {session['professor_name']} &nbsp;|&nbsp; Total Present: {len(records)} &nbsp;|&nbsp; Date: {date_str}</div>
<table><thead><tr><th>#</th><th>Student ID</th><th>Full Name</th><th>Method</th><th>Distance</th><th>Time</th><th>Note</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="footer">Generated by Attendance System · Session {session_id[:8]}</div>
<script>window.onload=()=>window.print();</script>
</body></html>"""
    return StreamingResponse(iter([html]), media_type="text/html", headers={"Content-Disposition": "inline"})


# Health
@router.get("/health")
def health():
    return {"status": "ok", "time": _now_utc().isoformat()}


# ── Course Summary (professor sees per-student attendance %) ───────────────────

@router.get("/courses")
def get_courses(secret: str = Query(...)):
    _check_secret(secret)
    prof_id = _get_professor_id(secret)
    courses = db.get_all_courses(professor_id=prof_id)
    return [{"course_name": c["course_name"], "group_name": c["group_name"]} for c in courses]


@router.get("/courses/{course_name}/summary")
def get_course_summary(course_name: str, group_name: str = Query(...), secret: str = Query(...), threshold: int = Query(default=80)):
    _check_secret(secret)
    prof_id = _get_professor_id(secret)
    rows = db.get_course_student_summary(course_name, group_name, professor_id=prof_id)
    result = []
    for r in rows:
        result.append({
            "student_id": r["student_id"],
            "full_name": r["full_name"],
            "telegram_username": r["telegram_username"],
            "total_sessions": r["total_sessions"],
            "attended": r["attended"],
            "percentage": r["percentage"],
            "at_risk": r["percentage"] < threshold,
        })
    return {
        "course_name": course_name,
        "total_students": len(result),
        "at_risk_count": sum(1 for r in result if r["at_risk"]),
        "threshold": threshold,
        "students": result,
    }


@router.get("/courses/{course_name}/summary/csv")
def export_course_summary_csv(course_name: str, group_name: str = Query(...), secret: str = Query(...), threshold: int = Query(default=80)):
    _check_secret(secret)
    prof_id = _get_professor_id(secret)
    rows = db.get_course_student_summary(course_name, group_name, professor_id=prof_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["#", "Student ID", "Full Name", "Telegram", "Attended", "Total Sessions", "Percentage", "Status"])
    for i, r in enumerate(rows, 1):
        status = "AT RISK" if r["percentage"] < threshold else "OK"
        writer.writerow([i, r["student_id"], r["full_name"],
                         f"@{r['telegram_username']}" if r["telegram_username"] else "",
                         r["attended"], r["total_sessions"], f"{r['percentage']}%", status])
    output.seek(0)
    filename = f"summary_{course_name.replace(' ', '_')}.csv"
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={filename}"})


# ── Attendance trend per session for a course+group ────────────────────────────

@router.get("/courses/{course_name}/trend")
def get_course_trend(course_name: str, group_name: str = Query(...), secret: str = Query(...)):
    _check_secret(secret)
    prof_id = _get_professor_id(secret)
    from db.database import get_conn
    with get_conn() as conn:
        prof_filter = "AND s.professor_id = ?" if prof_id else ""
        params = [course_name, group_name] + ([prof_id] if prof_id else [])
        rows = conn.execute(
            f"""SELECT s.id, s.created_at,
                      COUNT(a.id) as attended
               FROM sessions s
               LEFT JOIN attendance a ON a.session_id = s.id
               WHERE s.course_name = ? AND s.group_name = ? {prof_filter}
               GROUP BY s.id
               ORDER BY s.created_at ASC""",
            params
        ).fetchall()
    return [
        {
            "session_id": r["id"],
            "date": str(r["created_at"]).split("T")[0],
            "attended": r["attended"],
        }
        for r in rows
    ]


# ── Saved Locations ────────────────────────────────────────────────────────────

@router.get("/locations")
def get_locations(secret: str = Query(...)):
    _check_secret(secret)
    locs = db.get_locations()
    return [{"name": l["name"], "lat": l["lat"], "lng": l["lng"], "radius_meters": l["radius_meters"]} for l in locs]


@router.post("/locations")
def save_location(
    name: str = Query(...),
    lat: float = Query(...),
    lng: float = Query(...),
    radius_meters: int = Query(default=100),
    secret: str = Query(...)
):
    _check_secret(secret)
    if not name.strip():
        raise HTTPException(status_code=400, detail="Location name cannot be empty.")
    db.save_location(name.strip(), lat, lng, radius_meters)
    return {"success": True, "name": name}


@router.delete("/locations/{name}")
def delete_location(name: str, secret: str = Query(...)):
    _check_secret(secret)
    db.delete_location(name)
    return {"success": True}


# ── Admin Dashboard ────────────────────────────────────────────────────────────

from datetime import date, timedelta

def _since_date(period: str) -> str | None:
    today = date.today()
    if period == "1month":
        return (today - timedelta(days=30)).isoformat()
    elif period == "3months":
        return (today - timedelta(days=90)).isoformat()
    elif period == "6months":
        return (today - timedelta(days=180)).isoformat()
    return None  # all time


@router.get("/admin/overview")
def admin_overview(secret: str = Query(...), period: str = Query(default="all")):
    _check_admin_secret(secret)
    since = _since_date(period)
    return db.get_admin_overview(since)


@router.get("/admin/professors")
def admin_professors(secret: str = Query(...), period: str = Query(default="all")):
    _check_admin_secret(secret)
    since = _since_date(period)
    rows = db.get_professor_stats(since)
    return [
        {
            "professor_name": r["professor_name"],
            "total_sessions": r["total_sessions"],
            "total_groups": r["total_groups"],
            "total_attendances": r["total_attendances"],
            "avg_per_session": r["avg_per_session"],
        }
        for r in rows
    ]


@router.get("/admin/groups")
def admin_groups(secret: str = Query(...), period: str = Query(default="all")):
    _check_admin_secret(secret)
    since = _since_date(period)
    rows = db.get_group_stats(since)
    return [
        {
            "group_name": r["group_name"],
            "total_sessions": r["total_sessions"],
            "total_subjects": r["total_subjects"],
            "total_attendances": r["total_attendances"],
            "avg_per_session": r["avg_per_session"],
            "avg_rate": r["avg_rate"],
        }
        for r in rows
    ]


@router.get("/admin/subjects")
def admin_subjects(secret: str = Query(...), period: str = Query(default="all")):
    _check_admin_secret(secret)
    since = _since_date(period)
    rows = db.get_subject_stats(since)
    return [
        {
            "course_name": r["course_name"],
            "total_sessions": r["total_sessions"],
            "total_groups": r["total_groups"],
            "total_attendances": r["total_attendances"],
            "avg_per_session": r["avg_per_session"],
            "avg_rate": r["avg_rate"],
        }
        for r in rows
    ]


@router.get("/admin/matrix")
def admin_matrix(secret: str = Query(...), period: str = Query(default="all")):
    _check_admin_secret(secret)
    since = _since_date(period)
    rows = db.get_matrix_stats(since)
    return [
        {
            "group_name": r["group_name"],
            "course_name": r["course_name"],
            "total_sessions": r["total_sessions"],
            "total_attendances": r["total_attendances"],
            "avg_per_session": r["avg_per_session"],
            "avg_rate": r["avg_rate"],
            "enrolled": r["enrolled"],
        }
        for r in rows
    ]


# ── Professor Account Auth ─────────────────────────────────────────────────────

@router.post("/auth/professor/login")
def professor_login(username: str = Query(...), password: str = Query(...)):
    prof = db.verify_professor(username, password)
    if not prof:
        raise HTTPException(status_code=403, detail="Invalid username or password.")
    return {
        "success": True,
        "professor_id": prof["id"],
        "full_name": prof["full_name"],
        "username": prof["username"],
    }


# ── Professor Account Management (Admin only) ──────────────────────────────────

@router.get("/admin/professors/list")
def list_professors(secret: str = Query(...)):
    _check_admin_secret(secret)
    profs = db.get_all_professors()
    return [
        {
            "id": p["id"],
            "username": p["username"],
            "full_name": p["full_name"],
            "is_active": p["is_active"],
            "created_at": p["created_at"],
        }
        for p in profs
    ]


@router.post("/admin/professors/create")
def create_professor(
    username: str = Query(...),
    password: str = Query(...),
    full_name: str = Query(...),
    secret: str = Query(...)
):
    _check_admin_secret(secret)
    if not username.strip() or not password.strip() or not full_name.strip():
        raise HTTPException(status_code=400, detail="All fields are required.")
    success, msg = db.create_professor(username.strip(), password.strip(), full_name.strip())
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@router.patch("/admin/professors/{prof_id}")
def update_professor(
    prof_id: int,
    full_name: str = Query(default=None),
    password: str = Query(default=None),
    is_active: int = Query(default=None),
    secret: str = Query(...)
):
    _check_admin_secret(secret)
    prof = db.get_professor_by_id(prof_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Professor not found.")
    db.update_professor(prof_id, full_name=full_name, password=password, is_active=is_active)
    return {"success": True}


@router.delete("/admin/professors/{prof_id}")
def delete_professor(prof_id: int, secret: str = Query(...)):
    _check_admin_secret(secret)
    prof = db.get_professor_by_id(prof_id)
    if not prof:
        raise HTTPException(status_code=404, detail="Professor not found.")
    db.delete_professor(prof_id)
    return {"success": True}


@router.get("/professor/{prof_id}/sessions")
def professor_sessions(prof_id: int, username: str = Query(...), password: str = Query(...)):
    prof = db.verify_professor(username, password)
    if not prof or prof["id"] != prof_id:
        raise HTTPException(status_code=403, detail="Unauthorized.")
    sessions = db.get_sessions_by_professor(prof_id)
    return [
        {
            "session_id": s["id"],
            "course_name": s["course_name"],
            "group_name": s["group_name"],
            "professor_name": s["professor_name"],
            "created_at": s["created_at"],
            "expires_at": s["expires_at"],
            "is_active": s["is_active"],
            "attendance_count": s["attendance_count"],
        }
        for s in sessions
    ]


# ── Group Management (Admin) ───────────────────────────────────────────────────

@router.get("/admin/groups/list")
def list_groups(secret: str = Query(...)):
    _check_admin_secret(secret)
    groups = db.get_all_groups()
    return [{"id": g["id"], "name": g["name"], "enrollment": g["enrollment"],
             "student_count": g["student_count"], "created_at": g["created_at"]} for g in groups]

@router.post("/admin/groups/create")
def create_group(name: str = Query(...), enrollment: int = Query(...), secret: str = Query(...)):
    _check_admin_secret(secret)
    if not name.strip():
        raise HTTPException(status_code=400, detail="Group name is required.")
    success, msg = db.create_group(name.strip(), enrollment)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@router.patch("/admin/groups/{group_id}")
def update_group(group_id: int, name: str = Query(default=None),
                 enrollment: int = Query(default=None), secret: str = Query(...)):
    _check_admin_secret(secret)
    if not db.get_group_by_id(group_id):
        raise HTTPException(status_code=404, detail="Group not found.")
    db.update_group(group_id, name=name, enrollment=enrollment)
    return {"success": True}

@router.delete("/admin/groups/{group_id}")
def delete_group(group_id: int, secret: str = Query(...)):
    _check_admin_secret(secret)
    if not db.get_group_by_id(group_id):
        raise HTTPException(status_code=404, detail="Group not found.")
    db.delete_group(group_id)
    return {"success": True}

@router.get("/admin/groups/{group_id}/students")
def get_group_students(group_id: int, secret: str = Query(...)):
    _check_admin_secret(secret)
    students = db.get_students_in_group(group_id)
    return [{"id": s["id"], "student_id": s["student_id"], "full_name": s["full_name"],
             "telegram_username": s["telegram_username"]} for s in students]

@router.patch("/admin/students/{student_db_id}")
def update_student(student_db_id: int, full_name: str = Query(default=None),
                   student_id: str = Query(default=None), secret: str = Query(...)):
    _check_admin_secret(secret)
    db.update_student(student_db_id, full_name=full_name, student_id=student_id)
    return {"success": True}

@router.delete("/admin/students/{student_db_id}")
def delete_student(student_db_id: int, secret: str = Query(...)):
    _check_admin_secret(secret)
    db.delete_student(student_db_id)
    return {"success": True}

# Public endpoint for bot to fetch groups
@router.get("/groups")
def get_groups_public():
    groups = db.get_all_groups()
    return [{"id": g["id"], "name": g["name"], "enrollment": g["enrollment"]} for g in groups]
