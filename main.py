import asyncio
import logging
import socket
import uvicorn
from aiogram import Bot

from braincam.config import settings
from braincam.db.session import init_db
from braincam.web.app import app
from braincam.bot.main_bot import dp
from braincam.services.scheduler_service import BrainCamScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("braincam.main")

def find_available_port(start_port: int = 8000) -> int:
    """Finds first available open port to prevent Errno 10048 conflicts"""
    port = start_port
    while port < start_port + 20:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                port += 1
    return start_port

async def run_web():
    """Runs FastAPI web server"""
    config = uvicorn.Config(
        app=app,
        host=settings.HOST,
        port=settings.PORT,
        log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()

async def run_bot_and_scheduler():
    """Runs Telegram Bot polling and background notification scheduler"""
    if not settings.TELEGRAM_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN.startswith("your_"):
        logger.warning("TELEGRAM_BOT_TOKEN is not configured. Telegram bot skipped.")
        return

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    logger.info("Starting BrainCam AI Telegram Bot & Scheduler...")

    await asyncio.gather(
        dp.start_polling(bot),
        BrainCamScheduler.start(bot)
    )

async def main():
    # Automatically ensure port is free
    active_port = find_available_port(settings.PORT)
    if active_port != settings.PORT:
        logger.warning(f"⚠️ Порт {settings.PORT} занят другой программой. Автоматически переключаюсь на порт {active_port}!")
        settings.PORT = active_port
        settings.WEB_BASE_URL = f"http://localhost:{active_port}"

    logger.info("=" * 65)
    logger.info("🚀 Starting BrainCam AI — Make Every Camera Intelligent")
    logger.info(f"Owner / Admin: @{settings.ADMIN_TELEGRAM_USERNAME}")
    logger.info(f"AI Vision Model: {settings.GEMINI_MODEL}")
    logger.info(f"Payment Card (VISA): {settings.VISA_CARD_NUMBER} ({settings.VISA_CARD_HOLDER})")
    logger.info(f"Web Dashboard & Mini App: http://localhost:{settings.PORT}")
    logger.info("=" * 65)

    # Initialize DB tables
    await init_db()

    # Run Web Dashboard and Telegram Bot concurrently
    await asyncio.gather(
        run_web(),
        run_bot_and_scheduler()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("BrainCam AI stopped gracefully.")
