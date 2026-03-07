import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import init_db
from bot.handlers import build_app

async def main():
    init_db()
    print("[Bot] Starting polling...")
    app = build_app()
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    # Keep running until cancelled
    await app.updater.idle()
    await app.stop()
    await app.shutdown()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
