"""Webhook режим + health check endpoint"""
import logging
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

try:
    from app.config import BOT_TOKEN, ADMIN_IDS, LOG_LEVEL, LOG_FILE, PROXY_URL
    from app.database import db_pool
    from app.init_db import init_db
    from app.migrations import run_migrations
    from app.handlers.user_handlers import user_router
    from app.handlers.cart_handler import cart_router
    from app.handlers.admin_handler import admin_router
    from app.handlers.common_handler import common_router
    from app.middleware.rate_limit import RateLimitMiddleware
except ImportError as e:
    import logging
    logging.error(f"Ошибка импорта в webhook_server: {e}")
    # Fallback значения для запуска
    BOT_TOKEN = None
    ADMIN_IDS = []
    LOG_LEVEL = "INFO"
    LOG_FILE = "bot.log"
    PROXY_URL = None
    user_router = None
    cart_router = None
    admin_router = None
    common_router = None
    RateLimitMiddleware = None

logger = logging.getLogger(__name__)

# Health check состояние
bot_health = {
    "status": "starting",
    "last_poll": None,
    "errors": 0,
    "uptime": None
}


async def health_check(request):
    """Health check endpoint"""
    import time
    from datetime import datetime

    data = {
        "status": bot_health["status"],
        "uptime": bot_health["uptime"],
        "last_poll": bot_health["last_poll"],
        "errors": bot_health["errors"]
    }

    if bot_health["status"] == "running":
        return web.json_response(data, status=200)
    else:
        return web.json_response(data, status=503)


async def readiness_check(request):
    """Readiness check — готов ли бот принимать запросы"""
    if bot_health["status"] == "running":
        return web.json_response({"ready": True}, status=200)
    return web.json_response({"ready": False}, status=503)


async def admin_status(request):
    """Статус для админа (с токеном)"""
    token = request.query.get("token", "")
    admin_token = request.app.get("admin_token", "secret")

    if token != admin_token:
        return web.json_response({"error": "Unauthorized"}, status=401)

    data = {
        **bot_health,
        "database_pool": len(db_pool._connections) if db_pool._initialized else 0
    }
    return web.json_response(data)


def register_routers(dp: Dispatcher):
    """Регистрация роутеров"""
    dp.message.middleware(RateLimitMiddleware(rate=0.5))
    dp.callback_query.middleware(RateLimitMiddleware(rate=0.3))

    dp.include_router(common_router)
    dp.include_router(user_router)
    dp.include_router(cart_router)
    dp.include_router(admin_router)

    logger.info("Роутеры зарегистрированы")


async def on_startup(app: web.Application):
    """Старт webhook сервера"""
    import time

    bot_health["uptime"] = time.time()

    # Инициализация
    await db_pool.initialize()

    # Миграции вместо init_db
    await run_migrations()

    register_routers(app["dp"])

    bot = app["bot"]
    me = await bot.get_me()
    logger.info(f"Бот запущен: @{me.username}")

    # Установка webhook
    webhook_url = app["webhook_url"]
    await bot.set_webhook(webhook_url)
    logger.info(f"Webhook установлен: {webhook_url}")

    bot_health["status"] = "running"
    bot_health["errors"] = 0


async def on_shutdown(app: web.Application):
    """Остановка"""
    bot = app["bot"]
    await bot.delete_webhook()
    await db_pool.close_all()
    bot_health["status"] = "stopped"
    logger.info("Бот остановлен")


async def run_webhook(
    host: str = "0.0.0.0",
    port: int = 8080,
    webhook_path: str = "/webhook",
    webhook_url: str = None,
    admin_token: str = "secret"
):
    """Запуск бота в webhook режиме"""

    # Настройка логирования
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

    # Сессия
    session = AiohttpSession()
    if PROXY_URL:
        session.proxy = PROXY_URL

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML), session=session)
    dp = Dispatcher()

    # Error handler
    @dp.errors()
    async def errors_handler(exception, update, router):
        import logging
        logging.error(f"Ошибка: {exception}", exc_info=True)
        bot_health["errors"] += 1

        if bot_health["errors"] > 10:
            bot_health["status"] = "degraded"

        return True

    # Webhook URL
    if not webhook_url:
        webhook_url = f"https://your-domain.com{webhook_path}"

    # aiohttp приложение
    app = web.Application()
    app["bot"] = bot
    app["dp"] = dp
    app["webhook_url"] = webhook_url
    app["admin_token"] = admin_token

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    # Health check endpoints
    app.router.add_get("/health", health_check)
    app.router.add_get("/ready", readiness_check)
    app.router.add_get("/admin/status", admin_status)

    # Webhook handler
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=webhook_path)

    setup_application(app, dp, skip_updates=True)

    # Запуск
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info(f"Webhook сервер запущен на {host}:{port}")

    # Бесконечный цикл
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        await runner.cleanup()


if __name__ == "__main__":
    import os

    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))
    ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "secret")

    asyncio.run(run_webhook(
        webhook_url=WEBHOOK_URL,
        port=WEBHOOK_PORT,
        admin_token=ADMIN_TOKEN
    ))
