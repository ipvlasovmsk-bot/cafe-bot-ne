"""Middleware: rate limiting, проверка доступа"""
import logging
import time
from typing import Dict
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from aiogram.dispatcher.event.handler import HandlerObject

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseMiddleware):
    """Защита от спама — не более N запросов в секунду"""

    def __init__(self, rate: float = 0.5):
        """rate — минимальный интервал между запросами в секундах"""
        self.rate = rate
        self._user_timestamps: Dict[int, float] = {}

    async def __call__(
        self,
        handler,
        event,
        data
    ) -> bool | None:
        user_id = None

        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id

        if user_id is None:
            return await handler(event, data)

        now = time.time()
        last_time = self._user_timestamps.get(user_id, 0)

        if now - last_time < self.rate:
            # Слишком частый запрос — игнорируем
            logger.debug(f"Rate limit для пользователя {user_id}")
            return None

        self._user_timestamps[user_id] = now
        return await handler(event, data)


class AdminAccessMiddleware(BaseMiddleware):
    """Проверка прав администратора"""

    def __init__(self, admin_ids: list[int]):
        self.admin_ids = set(admin_ids)

    async def __call__(
        self,
        handler,
        event,
        data
    ) -> bool | None:
        user_id = None

        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id

        if user_id is None or user_id not in self.admin_ids:
            if isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ запрещён", show_alert=True)
            return None

        return await handler(event, data)
