"""Мониторинг — проверка что бот жив"""
import asyncio
import logging
import time
import sys
import json
import os
from datetime import datetime
from typing import Callable, Awaitable

logger = logging.getLogger("monitor")


class BotMonitor:
    """Мониторинг работоспособности бота"""

    def __init__(
        self,
        bot_token: str,
        chat_ids: list[int] = None,
        check_interval: int = 60,
        timeout: int = 10
    ):
        self.bot_token = bot_token
        self.chat_ids = chat_ids or []
        self.check_interval = check_interval
        self.timeout = timeout
        self.running = False
        self.consecutive_failures = 0
        self.max_failures = 3

    async def _check_bot(self) -> bool:
        """Проверка доступности бота через getMe"""
        import aiohttp

        url = f"https://api.telegram.org/bot{self.bot_token}/getMe"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=self.timeout)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("ok", False)
                    return False
        except Exception as e:
            logger.warning(f"Проверка не пройдена: {e}")
            return False

    async def _send_alert(self, message: str):
        """Отправка уведомления через Telegram Bot API напрямую"""
        if not self.chat_ids:
            logger.warning("Нет chat_ids для уведомлений")
            return

        import aiohttp

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        for chat_id in self.chat_ids:
            try:
                async with aiohttp.ClientSession() as session:
                    await session.post(url, json={
                        "chat_id": chat_id,
                        "text": message,
                        "parse_mode": "HTML"
                    }, timeout=aiohttp.ClientTimeout(total=self.timeout))
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление {chat_id}: {e}")

    async def _check_loop(self):
        """Основной цикл мониторинга"""
        logger.info("Мониторинг запущен")

        while self.running:
            try:
                is_alive = await self._check_bot()

                if is_alive:
                    if self.consecutive_failures > 0:
                        logger.info(f"Бот восстановлен после {self.consecutive_failures} ошибок")
                        await self._send_alert(
                            f"✅ <b>Бот восстановлен</b>\n\n"
                            f"Бот снова доступен после {self.consecutive_failures} неудачных проверок."
                        )
                    self.consecutive_failures = 0
                else:
                    self.consecutive_failures += 1
                    logger.warning(
                        f"Бот не отвечает (попытка {self.consecutive_failures}/{self.max_failures})"
                    )

                    if self.consecutive_failures >= self.max_failures:
                        await self._send_alert(
                            f"🚨 <b>Бот не отвечает!</b>\n\n"
                            f"Прошло {self.consecutive_failures} неудачных проверок.\n"
                            f"Время: {datetime.now().strftime('%H:%M:%S')}\n\n"
                            f"Проверьте:\n"
                            f"• Подключение к интернету\n"
                            f"• Процесс бота\n"
                            f"• Логи: bot.log"
                        )

            except Exception as e:
                logger.error(f"Ошибка мониторинга: {e}")

            await asyncio.sleep(self.check_interval)

    async def start(self):
        """Запустить мониторинг"""
        self.running = True
        await self._check_loop()

    async def stop(self):
        """Остановить мониторинг"""
        self.running = False
        logger.info("Мониторинг остановлен")


async def run_monitor(
    bot_token: str,
    admin_ids: list[int] = None,
    interval: int = 60
):
    """Запуск мониторинга как отдельного процесса"""
    import signal

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("monitor.log", encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    monitor = BotMonitor(
        bot_token=bot_token,
        chat_ids=admin_ids or [],
        check_interval=interval
    )

    # Обработка сигналов
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(sig, lambda: asyncio.create_task(monitor.stop()))

    await monitor.start()


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv

    load_dotenv()

    BOT_TOKEN = os.getenv("BOT_TOKEN")
    ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]
    INTERVAL = int(os.getenv("MONITOR_INTERVAL", "60"))

    if not BOT_TOKEN:
        print("Ошибка: BOT_TOKEN не установлен")
        sys.exit(1)

    asyncio.run(run_monitor(BOT_TOKEN, ADMIN_IDS, INTERVAL))
