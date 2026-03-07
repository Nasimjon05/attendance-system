"""
start.py — Single entry point for Railway deployment.
Runs the FastAPI server and Telegram bot concurrently in one process.
"""
import sys
import os
import asyncio
import threading
import uvicorn

# Make sure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config

def run_api():
    """Run FastAPI with uvicorn."""
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )

def run_bot():
    """Run Telegram bot in its own thread with its own event loop."""
    from bot.main import main as bot_main
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(bot_main())
    except Exception as e:
        print(f"[BOT] Error: {e}")
    finally:
        loop.close()

if __name__ == "__main__":
    print("[START] Launching Attendance System...")
    print(f"[START] BASE_URL = {config.BASE_URL}")

    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    print("[START] Telegram bot started.")

    # Run API in main thread (blocking)
    print("[START] Starting API server...")
    run_api()
