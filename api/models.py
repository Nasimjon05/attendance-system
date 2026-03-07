from pydantic import BaseModel, Field
from typing import Optional


class CreateSessionRequest(BaseModel):
    course_name: str = Field(..., example="Introduction to Computer Science")
    group_name: str = Field(..., example="Group A")
    professor_name: str = Field(..., example="Dr. Smith")
    lat: float = Field(..., example=41.2995)
    lng: float = Field(..., example=69.2401)
    radius_meters: int = Field(default=100, ge=20, le=500)
    validity_seconds: int = Field(default=90, ge=30, le=600)
    total_enrolled: int = Field(default=0, ge=0, description="Number of students enrolled in this class")
    secret: str = Field(..., description="Professor auth secret")


class SessionResponse(BaseModel):
    session_id: str
    course_name: str
    group_name: str
    professor_name: str
    expires_at: str
    qr_deep_link: str
    qr_image_base64: str


class AttendanceRecord(BaseModel):
    student_id: str
    full_name: str
    telegram_username: Optional[str]
    submitted_at: str
    distance_meters: Optional[float]
    method: str = "qr"
    note: Optional[str]


class SessionAttendanceResponse(BaseModel):
    session_id: str
    course_name: str
    group_name: str
    professor_name: str
    expires_at: str
    is_active: bool
    total_count: int
    records: list[AttendanceRecord]


class ManualOverrideRequest(BaseModel):
    student_id: str
    note: str = ""
    secret: str


class StudentSearchResult(BaseModel):
    student_id: str
    full_name: str
    telegram_username: Optional[str]


class SessionSummary(BaseModel):
    session_id: str
    course_name: str
    group_name: str
    professor_name: str
    created_at: str
    expires_at: str
    is_active: bool
    attendance_count: int
