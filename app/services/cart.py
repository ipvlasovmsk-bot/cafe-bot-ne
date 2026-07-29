"""Сервис корзины и оформления заказа"""
import logging
import json
from datetime import datetime
from typing import Optional

import aiosqlite

from app.services.loyalty import LoyaltyManager
from app.utils.thai_time import format_price

logger = logging.getLogger(__name__)


class CartService:
    """Управление корзиной и оформлением заказов"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_cart_items(self, user_id: int) -> list[dict]:
        """Получить items корзины пользователя"""
        cursor = await self.db.execute(
            "SELECT id, dish_id, dish_name, base_price, extra_price, ingredients FROM cart WHERE user_id = ?",
            (user_id,)
        )
        items = await cursor.fetchall()
        
        result = []
        for item in items:
            result.append({
                'id': item[0],
                'dish_id': item[1],
                'dish_name': item[2],
                'base_price': item[3],
                'extra_price': item[4],
                'ingredients': item[5]
            })
        return result

    async def get_cart_subtotal(self, user_id: int) -> int:
        """Получить сумму товаров в корзине"""
        cursor = await self.db.execute(
            "SELECT SUM(base_price + extra_price) FROM cart WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row[0] else 0

    async def create_order(self, user_id: int, items_json: str, address: str, 
                           delivery_time: str, subtotal: int, 
                           promo_discount: int = 0, points_used: int = 0) -> tuple[int, int, int]:
        """
        Создать заказ
        
        Returns:
            (order_id, cashback_points, referral_bonus)
        """
        lm = LoyaltyManager(self.db)
        
        # Расчет баллов кешбэка (5% от суммы заказа)
        cashback = await lm.calculate_cashback_points(subtotal - promo_discount)
        
        # Обработка реферала - начислить баллы пригласившему после первого заказа
        referral_bonus = await lm.complete_referral(user_id)
        
        total = max(0, subtotal - promo_discount - points_used)
        
        cursor = await self.db.execute(
            "INSERT INTO orders "
            "(user_id, items, address, total_price, status, points_earned, points_spent, "
            "discount_applied, promo_code, delivery_time, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, items_json, address, total, 'new', cashback + referral_bonus, points_used,
             promo_discount, None, delivery_time,
             datetime.now().isoformat(), datetime.now().isoformat())
        )
        order_id = cursor.lastrowid
        
        # Начисляем/списываем баллы
        if points_used > 0:
            await lm.spend_points(user_id, points_used, order_id)
        if cashback > 0:
            await lm.add_points(user_id, cashback, order_id)
        if referral_bonus > 0:
            logger.info(f"✅ Реферальный бонус: {referral_bonus} баллов начислено пользователю {user_id}")
        
        # Обновляем total_spent и уровень
        await self.db.execute(
            "UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?",
            (subtotal - promo_discount, user_id)
        )
        
        # Очищаем корзину
        await self.db.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
        
        return order_id, cashback, referral_bonus

    async def validate_points_usage(self, user_id: int, order_amount: int, points_to_use: int) -> tuple[bool, str]:
        """
        Проверить возможность использования баллов
        
        Returns:
            (успешно, сообщение)
        """
        lm = LoyaltyManager(self.db)
        return await lm.validate_points_usage(user_id, order_amount, points_to_use)

    async def get_max_usable_points(self, user_id: int, order_amount: int) -> int:
        """Получить максимальное количество баллов для заказа"""
        lm = LoyaltyManager(self.db)
        return await lm.get_max_usable_points(user_id, order_amount)
