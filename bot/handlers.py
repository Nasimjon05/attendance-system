import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from datetime import datetime, timezone

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters
)

import config
from db import database as db
from bot.location import is_within_radius

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Conversation states ────────────────────────────────────────────────────────
AWAITING_STUDENT_ID, AWAITING_FULL_NAME, AWAITING_GROUP = range(3)

# In-memory stores
_reg_cache: dict[int, dict] = {}
_pending_attendance: dict[int, str] = {}  # telegram_id -> session_id


# ── /start (plain handler, NOT inside ConversationHandler) ────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args

    # Case 1: Deep link from QR code — /start <session_id>
    if args:
        session_id = args[0]
        student = db.get_student_by_telegram(user.id)

        if not student:
            await update.message.reply_text(
                "👋 You're not registered yet!\n\n"
                "Please register first with /register\n"
                "Then scan the QR code again."
            )
            return

        session = db.get_session(session_id)
        if not session:
            await update.message.reply_text("❌ Invalid QR code. Ask your professor to regenerate it.")
            return

        expires_at = datetime.fromisoformat(session["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            await update.message.reply_text(
                "⏰ This QR code has expired.\n"
                "Ask your professor to show a new one."
            )
            return

        if not session["is_active"]:
            await update.message.reply_text("❌ This session is no longer active.")
            return

        # Store pending session and ask for location
        _pending_attendance[user.id] = session_id

        location_button = KeyboardButton("📍 Share My Location", request_location=True)
        reply_markup = ReplyKeyboardMarkup([[location_button]], resize_keyboard=True, one_time_keyboard=True)

        await update.message.reply_text(
            f"✅ Session found: *{session['course_name']}*\n"
            f"👨‍🏫 Professor: {session['professor_name']}\n\n"
            f"Please share your location to confirm attendance.\n"
            f"_(This verifies you are physically in the classroom)_",
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
        return

    # Case 2: Plain /start — welcome message
    student = db.get_student_by_telegram(user.id)
    if student:
        await update.message.reply_text(
            f"👋 Welcome back, *{student['full_name']}*!\n\n"
            f"🎓 Student ID: `{student['student_id']}`\n\n"
            f"Scan your professor's QR code to mark attendance.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "👋 Welcome to the *Attendance System*!\n\n"
            "To get started, register with:\n"
            "`/register`",
            parse_mode="Markdown",
        )


# ── Location handler (standalone, listens for any location message) ───────────

async def receive_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    location = update.message.location

    session_id = _pending_attendance.get(user.id)
    if not session_id:
        await update.message.reply_text(
            "❓ No active session. Please scan a QR code first.",
            reply_markup=ReplyKeyboardRemove()
        )
        return

    session = db.get_session(session_id)
    if not session:
        await update.message.reply_text("❌ Session not found.", reply_markup=ReplyKeyboardRemove())
        _pending_attendance.pop(user.id, None)
        return

    # Re-check expiry
    expires_at = datetime.fromisoformat(session["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires_at:
        await update.message.reply_text(
            "⏰ The QR code expired while you were submitting.\n"
            "Ask your professor to generate a new one.",
            reply_markup=ReplyKeyboardRemove()
        )
        _pending_attendance.pop(user.id, None)
        return

    within, distance = is_within_radius(
        classroom_lat=session["lat"],
        classroom_lng=session["lng"],
        student_lat=location.latitude,
        student_lng=location.longitude,
        radius_meters=session["radius_meters"],
    )

    student = db.get_student_by_telegram(user.id)

    if not within:
        await update.message.reply_text(
            f"❌ *Location check failed.*\n\n"
            f"You appear to be *{distance:.0f}m* from the classroom.\n"
            f"Allowed radius: {session['radius_meters']}m\n\n"
            f"Make sure you're inside the classroom and try again.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        _pending_attendance.pop(user.id, None)
        return

    success = db.record_attendance(
        session_id=session_id,
        student_id=student["student_id"],
        telegram_id=user.id,
        lat=location.latitude,
        lng=location.longitude,
        distance=distance,
    )

    _pending_attendance.pop(user.id, None)

    if success:
        await update.message.reply_text(
            f"✅ *Attendance recorded!*\n\n"
            f"📚 Course: {session['course_name']}\n"
            f"👤 Name: {student['full_name']}\n"
            f"📍 Distance from class: {distance:.0f}m\n"
            f"🕐 Time: {datetime.now().strftime('%H:%M:%S')}",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await update.message.reply_text(
            "ℹ️ Your attendance was already recorded for this session.",
            reply_markup=ReplyKeyboardRemove(),
        )


# ── /register flow ─────────────────────────────────────────────────────────────

async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    existing = db.get_student_by_telegram(user.id)
    if existing:
        await update.message.reply_text(
            f"✅ You're already registered as *{existing['full_name']}* "
            f"(ID: `{existing['student_id']}`).",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "📝 *Registration*\n\nPlease enter your *Student ID*:",
        parse_mode="Markdown"
    )
    return AWAITING_STUDENT_ID


async def receive_student_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    student_id = update.message.text.strip()
    if not student_id.isalnum() or len(student_id) < 4:
        await update.message.reply_text("⚠️ Invalid student ID. Please enter a valid alphanumeric ID.")
        return AWAITING_STUDENT_ID

    _reg_cache[update.effective_user.id] = {"student_id": student_id}
    await update.message.reply_text(
        f"Got it! Student ID: `{student_id}`\n\nNow enter your *Full Name*:",
        parse_mode="Markdown"
    )
    return AWAITING_FULL_NAME


async def receive_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    full_name = update.message.text.strip()

    if len(full_name) < 3 or not all(c.isalpha() or c.isspace() or c in "-'" for c in full_name):
        await update.message.reply_text("⚠️ Please enter a valid full name (letters only).")
        return AWAITING_FULL_NAME

    cached = _reg_cache.get(user.id, {})
    student_id = cached.get("student_id")
    if not student_id:
        await update.message.reply_text("Something went wrong. Please start over with /register")
        return ConversationHandler.END

    _reg_cache[user.id]["full_name"] = full_name

    # Fetch available groups directly from DB (no HTTP needed)
    try:
        raw = db.get_all_groups()
        groups = [{"id": g["id"], "name": g["name"], "enrollment": g["enrollment"]} for g in raw]
    except Exception as e:
        print(f"[BOT] Error fetching groups: {e}")
        groups = []

    if not groups:
        await update.message.reply_text(
            "⚠️ No groups have been created yet. Please ask your administrator to create groups first.",
            reply_markup=ReplyKeyboardRemove()
        )
        _reg_cache.pop(user.id, None)
        return ConversationHandler.END

    # Show groups as keyboard buttons
    keyboard = [[KeyboardButton(g["name"])] for g in groups]
    await update.message.reply_text(
        f"Great, *{full_name}*! 🎓\n\nNow select your *Group*:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return AWAITING_GROUP


async def receive_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_name = update.message.text.strip()

    # Validate group exists
    group = db.get_group_by_name(group_name)
    if not group:
        await update.message.reply_text("⚠️ Please select a valid group from the list.")
        return AWAITING_GROUP

    cached = _reg_cache.get(user.id, {})
    student_id = cached.get("student_id")
    full_name = cached.get("full_name")
    if not student_id or not full_name:
        await update.message.reply_text("Something went wrong. Please start over with /register")
        return ConversationHandler.END

    success = db.register_student(
        telegram_id=user.id,
        telegram_username=user.username,
        student_id=student_id,
        full_name=full_name,
    )

    if success:
        db.assign_student_group(user.id, group["id"])
        await update.message.reply_text(
            f"🎉 *Registration successful!*\n\n"
            f"👤 Name: {full_name}\n"
            f"🎓 Student ID: `{student_id}`\n"
            f"👥 Group: *{group_name}*\n\n"
            f"You can now scan QR codes to mark attendance.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await update.message.reply_text(
            "⚠️ This Telegram account or Student ID is already registered.\n"
            "Contact your administrator if this is an error.",
            reply_markup=ReplyKeyboardRemove()
        )

    _reg_cache.pop(user.id, None)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _reg_cache.pop(update.effective_user.id, None)
    _pending_attendance.pop(update.effective_user.id, None)
    await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ── Bot setup ──────────────────────────────────────────────────────────────────

def build_app() -> Application:
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    # Registration conversation
    reg_handler = ConversationHandler(
        entry_points=[CommandHandler("register", register_start)],
        states={
            AWAITING_STUDENT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_student_id)],
            AWAITING_FULL_NAME:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_full_name)],
            AWAITING_GROUP:      [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_group)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Plain handlers (no conversation needed)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mystats", my_stats))
    app.add_handler(reg_handler)
    app.add_handler(MessageHandler(filters.LOCATION, receive_location))

    return app


# ── /mystats ───────────────────────────────────────────────────────────────────

async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    student = db.get_student_by_telegram(user.id)

    if not student:
        await update.message.reply_text(
            "❓ You're not registered yet. Use /register first."
        )
        return

    stats = db.get_student_stats(student["student_id"])

    if not stats:
        await update.message.reply_text(
            f"👋 Hi *{student['full_name']}*!\n\n"
            f"No attendance records found yet.",
            parse_mode="Markdown"
        )
        return

    lines = []
    for row in stats:
        pct = row["percentage"]
        if pct >= 80:
            emoji = "✅"
        elif pct >= 60:
            emoji = "⚠️"
        else:
            emoji = "❌"
        group = f" — {row['group_name']}" if row['group_name'] else ""
        lines.append(
            f"{emoji} *{row['course_name']}*{group}\n"
            f"   {row['attended']}/{row['total_sessions']} classes — *{pct}%*"
        )

    msg = (
        f"📊 *Attendance Report*\n"
        f"👤 {student['full_name']} | `{student['student_id']}`\n"
        f"{'─' * 28}\n\n"
        + "\n\n".join(lines)
        + "\n\n_✅ ≥80%  ⚠️ 60–79%  ❌ <60%_"
    )

    await update.message.reply_text(msg, parse_mode="Markdown")
