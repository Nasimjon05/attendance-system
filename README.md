# University Attendance System

QR-code based attendance system with Telegram bot + location verification.

## How it works

1. **Professor** opens the dashboard, sets classroom location, generates a time-limited QR code
2. **Students** scan the QR → opens Telegram bot → bot asks for location → attendance recorded
3. **Professor** watches attendance populate live on the dashboard

---

## Setup

### 1. Create a Telegram Bot
- Message @BotFather on Telegram
- Send `/newbot` and follow prompts
- Copy the bot token

### 2. Configure environment
```bash
cp .env.example .env
# Edit .env with your values
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the API server
```bash
cd attendance-system
uvicorn api.main:app --reload --port 8000
```

### 5. Expose locally (for testing)
```bash
# Install ngrok: https://ngrok.com
ngrok http 8000
# Copy the https URL to BASE_URL in .env
```

### 6. Run the Telegram bot
```bash
python bot/main.py
```

### 7. Open the professor dashboard
Visit: `http://localhost:8000/dashboard`

---

## Project Structure

```
attendance-system/
├── bot/
│   ├── main.py          # Bot entry point
│   ├── handlers.py      # All bot conversation handlers
│   └── location.py      # Haversine distance calculation
├── api/
│   ├── main.py          # FastAPI app + static files
│   ├── routes.py        # API endpoints
│   └── models.py        # Pydantic request/response models
├── db/
│   ├── database.py      # SQLite helpers
│   └── schema.sql       # Table definitions
├── dashboard/
│   └── index.html       # Professor dashboard (single-page)
├── config.py            # All config from environment
├── requirements.txt
└── .env.example
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/sessions` | Create a session, get QR code |
| GET | `/api/sessions/{id}/attendance` | Get live attendance list |
| GET | `/api/health` | Health check |
| GET | `/dashboard` | Professor web UI |

---

## Student Flow (Telegram Bot)

| Command | Description |
|---------|-------------|
| `/start` | Welcome + registration prompt |
| `/register` | Register student ID + full name |
| `/cancel` | Cancel current operation |
| Scan QR | Opens bot with session → share location → attendance logged |

---

## Known Limitations (Prototype)

- GPS accuracy indoors can drift 20–50m; set radius accordingly (100–150m recommended)
- `PROFESSOR_SECRET` is a simple shared password — add JWT auth for production
- Bot state (`_pending_attendance`, `_reg_cache`) is in-memory; restarting bot clears it
- No admin panel for managing students or exporting reports yet
