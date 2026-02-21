import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import init_db
from bot.handlers import build_app

if __name__ == "__main__":
    init_db()
    print("[Bot] Starting polling...")
    app = build_app()
    app.run_polling(drop_pending_updates=True)
