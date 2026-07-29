"""Управление кухней — таймеры, загрузка"""
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import aiosqlite
from aiogram import Bot

from app.models import OrderStatus, OrderPriority, KitchenTimer
from app.config import KITCHEN_CAPACITY_PER_HOUR, PREP_TIME_BASE, PREP_TIME_PER_ITEM

logger = logging.getLogger(__name__)


class KitchenTimerManager:
    """Многоэтапные таймеры кухни"""

    STAGES = {
        'prep': ('🔪 Заготовка', 10),
        'cooking': ('👨‍🍳 Приготовление', 20),
        'assembly': ('📦 Сборка', 5),
        'packing': ('🥡 Упаковка', 3)
    }

    def __init__(self, db: aiosqlite.Connection, bot: Bot):
        self.db = db
        self.bot = bot
        self.active_timers: Dict[int, List[KitchenTimer]] = {}

    def calculate_prep_time(self, items: list[dict], priority: OrderPriority) -> int:
        """Расчёт времени приготовления"""
        base_time = PREP_TIME_BASE
        cooking_time = sum(
            item.get('prep_time', PREP_TIME_PER_ITEM) * item.get('complexity', 1)
            for item in items
        )
        total = base_time + cooking_time

        if priority == OrderPriority.VIP:
            total = int(total * 0.8)
        elif priority == OrderPriority.PREORDER:
            total = int(total * 1.2)

        return max(15, total)

    async def start_order_timer(self, order_id: int, items: list[dict], priority: OrderPriority):
        """Запуск многоэтапных таймеров"""
        total_time = self.calculate_prep_time(items, priority)
        stage_weights = {'prep': 0.2, 'cooking': 0.5, 'assembly': 0.2, 'packing': 0.1}

        current_time = datetime.now()
        timers = []

        for stage, (name, base_minutes) in self.STAGES.items():
            stage_time = int(total_time * stage_weights[stage])
            estimated_end = current_time + timedelta(minutes=stage_time)

            await self.db.execute(
                "INSERT INTO kitchen_timers "
                "(order_id, stage, start_time, estimated_end) VALUES (?, ?, ?, ?)",
                (order_id, stage, current_time.isoformat(), estimated_end.isoformat())
            )

            timers.append(KitchenTimer(
                order_id=order_id,
                stage=stage,
                start_time=current_time,
                estimated_end=estimated_end
            ))
            current_time = estimated_end

        self.active_timers[order_id] = timers
        logger.info(f"⏱️ Таймер заказа {order_id}: {total_time} мин, {len(timers)} этапов")

        # Запуск фонового мониторинга
        asyncio.create_task(self._monitor_order(order_id))

    async def _monitor_order(self, order_id: int):
        """Мониторинг прогресса заказа"""
        stage_transitions = {
            'prep': OrderStatus.COOKING,
            'cooking': OrderStatus.ASSEMBLY,
            'assembly': OrderStatus.READY,
        }

        for stage_name in self.STAGES:
            # Имитация времени этапа (в реальности — интеграция с кухонным дисплеем)
            await asyncio.sleep(60)

            await self.db.execute(
                "UPDATE kitchen_timers SET is_completed = 1, actual_end = ? "
                "WHERE order_id = ? AND stage = ?",
                (datetime.now().isoformat(), order_id, stage_name)
            )

            await self._notify_stage_change(order_id, stage_name)

            if stage_name in stage_transitions:
                await self._update_order_status(order_id, stage_transitions[stage_name])

    async def _notify_stage_change(self, order_id: int, stage: str):
        """Уведомление клиента о смене этапа"""
        cursor = await self.db.execute(
            "SELECT user_id FROM orders WHERE id = ?", (order_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return

        user_id = row[0]
        messages = {
            'prep': "🔪 Начинаем заготовку ингредиентов...",
            'cooking': "👨‍🍳 Ваш заказ готовится на кухне!",
            'assembly': "📦 Собираем ваш заказ...",
            'packing': "🥡 Упаковываем для доставки!"
        }

        try:
            await self.bot.send_message(user_id, messages.get(stage, ""))
        except Exception as e:
            logger.warning(f"Не удалось уведомить пользователя {user_id} об этапе {stage}: {e}")

    async def _update_order_status(self, order_id: int, status: OrderStatus):
        """Обновление статуса заказа"""
        await self.db.execute(
            "UPDATE orders SET status = ?, current_stage = ?, updated_at = ? WHERE id = ?",
            (status.value, status.value, datetime.now().isoformat(), order_id)
        )


class KitchenLoadManager:
    """Управление загрузкой кухни"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def check_capacity(self, delivery_time: datetime) -> Tuple[bool, int]:
        """Проверка доступности слота"""
        date_str = delivery_time.strftime("%Y-%m-%d")
        hour = delivery_time.hour

        cursor = await self.db.execute(
            "SELECT current_load, max_capacity, is_blocked FROM kitchen_load "
            "WHERE date = ? AND hour = ?",
            (date_str, hour)
        )
        row = await cursor.fetchone()

        if not row:
            await self.db.execute(
                "INSERT INTO kitchen_load (date, hour, max_capacity) VALUES (?, ?, ?)",
                (date_str, hour, KITCHEN_CAPACITY_PER_HOUR)
            )
            return True, KITCHEN_CAPACITY_PER_HOUR

        current_load, max_capacity, is_blocked = row
        if is_blocked:
            return False, 0

        available = max_capacity - current_load
        return available > 0, available

    async def reserve_slot(self, delivery_time: datetime) -> bool:
        """Бронирование слота"""
        can_reserve, _ = await self.check_capacity(delivery_time)
        if not can_reserve:
            return False

        date_str = delivery_time.strftime("%Y-%m-%d")
        hour = delivery_time.hour
        await self.db.execute(
            "UPDATE kitchen_load SET current_load = current_load + 1 WHERE date = ? AND hour = ?",
            (date_str, hour)
        )
        return True

    async def release_slot(self, delivery_time: datetime):
        """Освобождение слота"""
        date_str = delivery_time.strftime("%Y-%m-%d")
        hour = delivery_time.hour
        await self.db.execute(
            "UPDATE kitchen_load SET current_load = MAX(0, current_load - 1) "
            "WHERE date = ? AND hour = ?",
            (date_str, hour)
        )

    async def get_available_slots(self, date) -> list[int]:
        """Доступные слоты на дату"""
        date_str = date.strftime("%Y-%m-%d")
        slots = []

        for hour in range(10, 23):
            can_reserve, _ = await self.check_capacity(
                datetime.combine(date, datetime.min.time().replace(hour=hour))
            )
            if can_reserve:
                slots.append(hour)

        return slots

    async def block_slot(self, date, hour: int):
        """Блокировка слота админом"""
        date_str = date.strftime("%Y-%m-%d")
        await self.db.execute(
            "INSERT OR REPLACE INTO kitchen_load (date, hour, max_capacity, is_blocked) "
            "VALUES (?, ?, 0, 1)",
            (date_str, hour)
        )
