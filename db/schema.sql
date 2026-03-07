-- Students registered with the bot
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    telegram_username TEXT,
    student_id TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sessions created by professors
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,              -- UUID, also embedded in QR
    course_name TEXT NOT NULL,
    group_name TEXT NOT NULL DEFAULT '',
    professor_name TEXT NOT NULL,
    lat REAL NOT NULL,                -- Classroom latitude
    lng REAL NOT NULL,                -- Classroom longitude
    radius_meters INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,    -- QR code expiry
    is_active INTEGER DEFAULT 1
);

-- Attendance records
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    student_id TEXT NOT NULL REFERENCES students(student_id),
    telegram_id INTEGER,              -- NULL for manual overrides
    submitted_lat REAL,               -- NULL for manual overrides
    submitted_lng REAL,               -- NULL for manual overrides
    distance_meters REAL,             -- NULL for manual overrides
    method TEXT DEFAULT 'qr',         -- 'qr' or 'manual'
    note TEXT,                        -- Professor note for manual entries
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, student_id)    -- One submission per student per session
);

-- Saved classroom locations
CREATE TABLE IF NOT EXISTS locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    radius_meters INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
