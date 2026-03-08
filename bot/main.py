import sys, os, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import init_db
from bot.handlers import build_app

async def main():
    init_db()
    print("[Bot] Starting polling...")
    app = build_app()
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        print("[Bot] Polling active. Waiting for messages...")
        # Keep alive forever until process is killed
        await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
