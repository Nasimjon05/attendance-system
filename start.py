"""
start.py — Single entry point for Railway deployment.
Runs FastAPI and Telegram bot concurrently using asyncio.
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

async def run_bot():
    """Run Telegram bot."""
    from bot.main import main as bot_main
    try:
        print("[START] Bot starting...")
        await bot_main()
    except Exception as e:
        print(f"[BOT ERROR] {e}")
        import traceback
        traceback.print_exc()

async def run_api():
    """Run FastAPI with uvicorn."""
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    config_obj = uvicorn.Config(
        "api.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config_obj)
    print(f"[START] API starting on port {port}...")
    await server.serve()

async def main():
    print("[START] Launching Attendance System...")
    print(f"[START] BASE_URL = {config.BASE_URL}")
    print(f"[START] DB_PATH  = {config.DB_PATH}")

    # Run both concurrently
    await asyncio.gather(
        run_api(),
        run_bot(),
    )

if __name__ == "__main__":
    asyncio.run(main())
