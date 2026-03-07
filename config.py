import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ───────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "AttendanceBot")

# ── Server ─────────────────────────────────────────────────────────────────────
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", "8000")))  # Railway uses PORT

# Public base URL — set to Railway domain in production
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

# ── Database ───────────────────────────────────────────────────────────────────
# Default to /data/attendance.db on Railway (Volume mount), fallback for local
DB_PATH = os.getenv("DB_PATH", "/data/attendance.db" if os.path.isdir("/data") else "attendance.db")

# ── Attendance Rules ───────────────────────────────────────────────────────────
DEFAULT_QR_VALIDITY_SECONDS = int(os.getenv("QR_VALIDITY_SECONDS", "90"))
DEFAULT_RADIUS_METERS = int(os.getenv("DEFAULT_RADIUS_METERS", "100"))

# ── Security ───────────────────────────────────────────────────────────────────
PROFESSOR_SECRET = os.getenv("PROFESSOR_SECRET", "changeme123")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "admin123")
