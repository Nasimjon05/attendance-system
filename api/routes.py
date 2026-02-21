import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import base64
import io
from datetime import datetime, timedelta, timezone

import qrcode
from fastapi import APIRouter, HTTPException, Query

import config
from db import database as db
from api.models import (
    CreateSessionRequest, SessionResponse,
    SessionAttendanceResponse, AttendanceRecord
)

router = APIRouter()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _build_deep_link(session_id: str) -> str:
    """
    Telegram bot deep link. When student scans QR, opens bot with session_id as start param.
    Format: https://t.me/<BOT_USERNAME>?start=<session_id>
    """
    return f"https://t.me/{config.BOT_USERNAME}?start={session_id}"


def _generate_qr_base64(data: str) -> str:
    """Generate QR code PNG and return as base64 string."""
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


# ── Create Session (Professor generates QR) ────────────────────────────────────

@router.post("/sessions", response_model=SessionResponse)
def create_session(req: CreateSessionRequest):
    if req.secret != config.PROFESSOR_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret.")

    session_id = str(uuid.uuid4())
    now = _now_utc()
    expires_at = now + timedelta(seconds=req.validity_seconds)
    expires_str = expires_at.isoformat()

    db.create_session(
        session_id=session_id,
        course_name=req.course_name,
        professor_name=req.professor_name,
        lat=req.lat,
        lng=req.lng,
        radius_meters=req.radius_meters,
        expires_at=expires_str,
    )

    deep_link = _build_deep_link(session_id)
    qr_b64 = _generate_qr_base64(deep_link)

    return SessionResponse(
        session_id=session_id,
        course_name=req.course_name,
        professor_name=req.professor_name,
        expires_at=expires_str,
        qr_deep_link=deep_link,
        qr_image_base64=qr_b64,
    )


# ── Get Attendance for a Session (live polling) ────────────────────────────────

@router.get("/sessions/{session_id}/attendance", response_model=SessionAttendanceResponse)
def get_session_attendance(session_id: str, secret: str = Query(...)):
    if secret != config.PROFESSOR_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret.")

    session = db.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    records_raw = db.get_attendance_for_session(session_id)
    records = [
        AttendanceRecord(
            student_id=r["student_id"],
            full_name=r["full_name"],
            telegram_username=r["telegram_username"],
            submitted_at=r["submitted_at"],
            distance_meters=round(r["distance_meters"], 1),
        )
        for r in records_raw
    ]

    # Check if session is still active (not expired)
    expires_at = datetime.fromisoformat(session["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    is_active = session["is_active"] == 1 and _now_utc() < expires_at

    return SessionAttendanceResponse(
        session_id=session_id,
        course_name=session["course_name"],
        professor_name=session["professor_name"],
        expires_at=session["expires_at"],
        is_active=is_active,
        total_count=len(records),
        records=records,
    )


# ── Health check ───────────────────────────────────────────────────────────────

@router.get("/health")
def health():
    return {"status": "ok", "time": _now_utc().isoformat()}
