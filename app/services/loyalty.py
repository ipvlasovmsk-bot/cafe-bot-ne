"""Система лояльности"""
import logging
import hashlib
from datetime import datetime
from typing import Optional

import aiosqlite
from aiogram import Bot

from app.models import LoyaltyLevel
from app.config import (
    LOYALTY_BRONZE_THRESHOLD, LOYALTY_SILVER_THRESHOLD, LOYALTY_GOLD_THRESHOLD,
    LOYALTY_CASHBACK_BRONZE, LOYALTY_CASHBACK_SILVER, LOYALTY_CASHBACK_GOLD,
    REFERRAL_BONUS
)

# Константы новой системы лояльности
WELCOME_BONUS = 50  # Баллов за регистрацию
REFERRAL_BONUS_ON_ORDER = 50  # Баллов за приглашение (после оплаты заказа)
MIN_ORDER_FOR_POINTS_USAGE = 300  # Минимальная сумма заказа для использования баллов
MAX_POINTS_USAGE_PERCENT = 25  # Максимальный % от заказа, который можно оплатить баллами
POINTS_CASHBACK_PERCENT = 5  # Процент от заказа в виде баллов

logger = logging.getLogger(__name__)


class LoyaltySystem:
    """Статические методы для расчёта лояльности"""

    @staticmethod
    def calculate_level(total_spent: int) -> LoyaltyLevel:
        if total_spent >= LOYALTY_GOLD_THRESHOLD:
            return LoyaltyLevel.GOLD
        elif total_spent >= LOYALTY_SILVER_THRESHOLD:
            return LoyaltyLevel.SILVER
        elif total_spent >= LOYALTY_BRONZE_THRESHOLD:
            return LoyaltyLevel.BRONZE
        return LoyaltyLevel.NONE

    @staticmethod
    def get_cashback_percent(level: LoyaltyLevel) -> float:
        return {
            LoyaltyLevel.NONE: 0,
            LoyaltyLevel.BRONZE: LOYALTY_CASHBACK_BRONZE,
            LoyaltyLevel.SILVER: LOYALTY_CASHBACK_SILVER,
            LoyaltyLevel.GOLD: LOYALTY_CASHBACK_GOLD
        }.get(level, 0)

    @staticmethod
    def generate_referral_code(user_id: int) -> str:
        hash_val = hashlib.md5(str(user_id).encode()).hexdigest()[:4].upper()
        return f"CAFE{user_id}{hash_val}"


class LoyaltyManager:
    """Управление лояльностью пользователя"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_user_stats(self, user_id: int) -> Optional[dict]:
        """Получить статистику лояльности пользователя"""
        cursor = await self.db.execute(
            "SELECT total_spent, loyalty_points, loyalty_level, referral_code, referred_by "
            "FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None

        level = LoyaltyLevel(row[2])
        next_level = None
        next_threshold = None

        if level == LoyaltyLevel.NONE:
            next_level = "BRONZE"
            next_threshold = LOYALTY_BRONZE_THRESHOLD
        elif level == LoyaltyLevel.BRONZE:
            next_level = "SILVER"
            next_threshold = LOYALTY_SILVER_THRESHOLD
        elif level == LoyaltyLevel.SILVER:
            next_level = "GOLD"
            next_threshold = LOYALTY_GOLD_THRESHOLD

        progress = 0
        if next_threshold:
            progress = min(100, int((row[0] / next_threshold) * 100))

        return {
            "total_spent": row[0],
            "points": row[1],
            "level": level.value,
            "level_name": self._get_level_name(level),
            "cashback": int(LoyaltySystem.get_cashback_percent(level) * 100),
            "next_level": next_level,
            "next_threshold": next_threshold,
            "progress": progress,
            "referral_code": row[3],
            "referred_by": row[4]
        }

    @staticmethod
    def _get_level_name(level: LoyaltyLevel) -> str:
        return {
            LoyaltyLevel.NONE: "🆕 Новичок",
            LoyaltyLevel.BRONZE: "🥉 Бронза",
            LoyaltyLevel.SILVER: "🥈 Серебро",
            LoyaltyLevel.GOLD: "🥇 Золото"
        }.get(level, "Неизвестно")

    async def add_points(self, user_id: int, amount: int, order_id: int | None = None):
        """Начислить баллы"""
        await self.db.execute(
            "UPDATE users SET loyalty_points = loyalty_points + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await self.db.execute(
            "INSERT INTO points_history (user_id, amount, type, order_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, "earn", order_id, datetime.now().isoformat())
        )

    async def calculate_cashback_points(self, order_amount: int) -> int:
        """Рассчитать баллы кешбэка за заказ (5% от суммы)"""
        return int(order_amount * POINTS_CASHBACK_PERCENT / 100)

    async def spend_points(self, user_id: int, amount: int, order_id: int) -> bool:
        """Списать баллы"""
        cursor = await self.db.execute(
            "SELECT loyalty_points FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if not row or row[0] < amount:
            return False

        await self.db.execute(
            "UPDATE users SET loyalty_points = loyalty_points - ? WHERE user_id = ?",
            (amount, user_id)
        )
        await self.db.execute(
            "INSERT INTO points_history (user_id, amount, type, order_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, -amount, "spend", order_id, datetime.now().isoformat())
        )
        return True

    async def validate_points_usage(self, user_id: int, order_amount: int, points_to_use: int) -> tuple[bool, str]:
        """
        Проверить возможность использования баллов
        
        Args:
            user_id: ID пользователя
            order_amount: Сумма заказа в батах
            points_to_use: Количество баллов для использования
            
        Returns:
            (успешно, сообщение)
        """
        # Проверка минимальной суммы заказа
        if order_amount < MIN_ORDER_FOR_POINTS_USAGE:
            return False, f"Минимальная сумма для использования баллов: {MIN_ORDER_FOR_POINTS_USAGE} бат"
        
        # Проверка максимального процента использования
        max_points_allowed = int(order_amount * MAX_POINTS_USAGE_PERCENT / 100)
        if points_to_use > max_points_allowed:
            return False, f"Максимум {MAX_POINTS_USAGE_PERCENT}% от заказа ({max_points_allowed} баллов)"
        
        # Проверка баланса баллов пользователя
        cursor = await self.db.execute(
            "SELECT loyalty_points FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if not row or row[0] < points_to_use:
            return False, "Недостаточно баллов"
        
        return True, "OK"

    async def get_max_usable_points(self, user_id: int, order_amount: int) -> int:
        """Получить максимальное количество баллов, которое можно использовать для заказа"""
        cursor = await self.db.execute(
            "SELECT loyalty_points FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        user_points = row[0] if row else 0
        
        # Ограничение по % от заказа
        max_by_percent = int(order_amount * MAX_POINTS_USAGE_PERCENT / 100)
        
        # Возвращаем минимум из доступных баллов и ограничения по %
        return min(user_points, max_by_percent)

    async def process_referral(self, new_user_id: int, referral_code: str) -> bool:
        """Обработка реферального кода при регистрации"""
        cursor = await self.db.execute(
            "SELECT user_id FROM users WHERE referral_code = ?", (referral_code,)
        )
        referrer = await cursor.fetchone()

        if not referrer or referrer[0] == new_user_id:
            return False

        # Не начисляем баллы сразу, только отметим реферала
        await self.db.execute(
            "UPDATE users SET referred_by = ? WHERE user_id = ?",
            (referrer[0], new_user_id)
        )

        logger.info(f"✅ Реферал записан: {referrer[0]} -> {new_user_id}, баллы будут после первого заказа")
        return True

    async def complete_referral(self, new_user_id: int) -> int:
        """
        Завершить реферальную программу - начислить баллы приглашенному после первого оплаченного заказа
        
        Returns:
            Количество начисленных баллов
        """
        cursor = await self.db.execute(
            "SELECT referred_by FROM users WHERE user_id = ?", (new_user_id,)
        )
        row = await cursor.fetchone()
        
        if not row or not row[0]:
            return 0
        
        referrer_id = row[0]
        
        # Начисляем баллы рефереру
        await self.add_points(referrer_id, REFERRAL_BONUS_ON_ORDER, None)
        
        # Очищаем реферальную связь, чтобы не начислять повторно
        await self.db.execute(
            "UPDATE users SET referred_by = NULL WHERE user_id = ?", (new_user_id,)
        )
        
        logger.info(f"✅ Реферальный заказ: {referrer_id} получил {REFERRAL_BONUS_ON_ORDER} баллов")
        return REFERRAL_BONUS_ON_ORDER

    async def check_birthday(self, user_id: int) -> Optional[int]:
        """Проверка дня рождения — возвращает % скидки или None"""
        cursor = await self.db.execute(
            "SELECT birth_date FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        if not row or not row[0]:
            return None

        try:
            birth = datetime.strptime(row[0], "%d.%m.%Y")
            today = datetime.now()
            if birth.day == today.day and birth.month == today.month:
                return 15  # 15% скидка
        except ValueError:
            logger.warning(f"Некорректная дата рождения у пользователя {user_id}: {row[0]}")

        return None
