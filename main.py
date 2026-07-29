"""Главный файл запуска бота"""
import asyncio
import logging
import os
import signal
import sys
from datetime import datetime, timedelta

# Добавляем директорию скрипта в пути импорта (для Colab и других сред)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import BOT_TOKEN, ADMIN_IDS, LOG_LEVEL, LOG_FILE, PROXY_URL
from app.database import db_pool
from app.init_db import init_db
from app.migrations import run_migrations
from app.utils.thai_time import format_price
from app.handlers.user_handlers import user_router
from app.handlers.cart_handler import cart_router
from app.handlers.payment_check_handler import payment_check_router, set_bot_instance
from app.handlers.admin_handler import admin_router as admin_handler
from app.handlers.admin_check_handler import admin_check_router
from app.handlers.admin_order_handler import admin_order_router
from app.handlers.admin_reservation_handler import admin_reservation_router
from app.handlers.reservation_handler import reservation_router
from app.handlers.dish_constructor_handler import constructor_router
from app.handlers.common_handler import common_router
from app.middleware.rate_limit import RateLimitMiddleware
from aiogram.client.session.aiohttp import AiohttpSession

# ==================== ЛОГИРОВАНИЕ ====================
class SafeFormatter(logging.Formatter):
    """Форматтер, заменяющий эмодзи для Windows"""
    def format(self, record):
        msg = super().format(record)
        if sys.platform == 'win32':
            # Заменяем эмодзи на ASCII-совместимые
            replacements = {
                '\u2705': '[OK]',
                '\U0001f916': '[BOT]',
                '\U0001f50c': '[OFF]',
                '\u274c': '[ERR]',
                '\u26a0\ufe0f': '[WARN]',
            }
            for emoji, repl in replacements.items():
                msg = msg.replace(emoji, repl)
        return msg

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(SafeFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
console_handler.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger(__name__)

# ==================== ИНИЦИАЛИЗАЦИЯ ====================

# Настройка сессии с прокси (если нужен)
if PROXY_URL:
    session = AiohttpSession(proxy=PROXY_URL)
    logger.info(f"[WARN] Используется прокси: {PROXY_URL}")
else:
    session = AiohttpSession()

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML), session=session)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# ==================== ОБРАБОТЧИК ОШИБОК ====================
@dp.errors()
async def errors_handler(exception: Exception, update=None, router=None):
    """Глобальный обработчик ошибок"""
    logger.error(f"Ошибка: {exception}", exc_info=True)
    return True


# ==================== РЕГИСТРАЦИЯ РОУТЕРОВ ====================
def register_routers():
    """Регистрация всех роутеров в правильном порядке"""
    # Middleware
    dp.message.middleware(RateLimitMiddleware(rate=0.5))
    dp.callback_query.middleware(RateLimitMiddleware(rate=0.3))

    # Роутеры (порядок важен — сначала специфичные, затем fallback)
    dp.include_router(user_router)
    dp.include_router(cart_router)
    dp.include_router(payment_check_router)  # Обработчики чеков пользователей
    dp.include_router(admin_handler)
    dp.include_router(admin_check_router)  # Админ-обработчики чеков
    dp.include_router(admin_order_router)  # Админ-обработчики заказов
    dp.include_router(reservation_router)
    dp.include_router(admin_reservation_router)
    dp.include_router(constructor_router)
    dp.include_router(common_router)  # Fallback — в конце, чтобы ловить только необработанные

    logger.info("✅ Роутеры зарегистрированы")


# ==================== ПЛАНИРОВЩИК ====================
async def daily_tasks():
    """Ежедневные задачи"""
    logger.info("Выполнение ежедневных задач...")

    from app.database import get_db
    from app.services.loyalty import LoyaltySystem

    async with get_db() as db:
        # Обновление уровней лояльности
        cursor = await db.execute("SELECT user_id, total_spent FROM users")
        users = await cursor.fetchall()

        for user_id, total_spent in users:
            new_level = LoyaltySystem.calculate_level(total_spent).value
            await db.execute(
                "UPDATE users SET loyalty_level = ? WHERE user_id = ?",
                (new_level, user_id)
            )

        # Очистка старых корзин (> 3 дней)
        three_days_ago = (datetime.now() - timedelta(days=3)).isoformat()
        await db.execute("DELETE FROM cart WHERE added_at < ?", (three_days_ago,))

        logger.info("✅ Ежедневные задачи выполнены")


async def daily_broadcast():
    """Ежедневная рассылка блюда дня"""
    from app.database import get_db

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT user_id FROM subscribers WHERE is_active = 1 AND push_consent = 1"
        )
        subscribers = await cursor.fetchall()

        today = datetime.now().strftime("%Y-%m-%d")
        cursor = await db.execute(
            "SELECT m.* FROM dish_of_day dod JOIN menu m ON dod.dish_id = m.id WHERE dod.date = ?",
            (today,)
        )
        dish = await cursor.fetchone()

        if not dish:
            logger.info("Блюдо дня не установлено")
            return

        text = (
            f"🍽️ <b>Блюдо дня!</b>\n\n"
            f"<b>{dish[1]}</b>\n"
            f"{dish[2]}\n\n"
            f"💰 {format_price(dish[3])}\n"
            f"⭐ {dish[12] if len(dish) > 12 else 5.0}/5\n\n"
            f"Закажите сейчас по специальной цене!"
        )

        for (user_id,) in subscribers:
            try:
                await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"Не удалось отправить {user_id}: {e}")


def setup_scheduler():
    """Настройка планировщика"""
    scheduler.add_job(daily_tasks, CronTrigger(hour=0, minute=0))
    scheduler.add_job(daily_broadcast, CronTrigger(hour=10, minute=0))
    logger.info("✅ Планировщик настроен")


# ==================== ЗАПУСК ====================
async def shutdown(signal_type=None):
    """Корректное завершение"""
    logger.info(f"Получен сигнал {signal_type}, завершение...")
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await db_pool.close_all()
    await bot.session.close()
    logger.info("Бот остановлен")


async def main():
    """Точка входа"""
    try:
        # Инициализация
        await db_pool.initialize()

        # Миграции (или init_db для первого запуска)
        import os
        if os.path.exists("cafe_ecosystem.db"):
            await run_migrations()
        else:
            await init_db()
            await run_migrations()

        register_routers()
        setup_scheduler()
        scheduler.start()

        # Инициализация бота для обработчиков чеков
        set_bot_instance(bot)

        logger.info(f"[BOT] Бот запущен (@{(await bot.get_me()).username})")
        logger.info(f"Админы: {ADMIN_IDS}")

        # Обработчики сигналов
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s.name)))

        # Запуск polling
        await dp.start_polling(bot)

    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}", exc_info=True)
    finally:
        await shutdown()


if __name__ == "__main__":
    asyncio.run(main())