import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "AttendanceBot")
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
DB_PATH = os.getenv("DB_PATH", "attendance.db")
DEFAULT_QR_VALIDITY_SECONDS = int(os.getenv("QR_VALIDITY_SECONDS", "90"))
DEFAULT_RADIUS_METERS = int(os.getenv("DEFAULT_RADIUS_METERS", "100"))
PROFESSOR_SECRET = os.getenv("PROFESSOR_SECRET", "changeme123")
