import asyncio
import logging
import signal
import sys
import json
import re
import math
import hashlib
import random
from datetime import datetime, timedelta, time as dt_time
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import sqlite3

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.enums import ParseMode
import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import os
from dotenv import load_dotenv

# ==================== КОНФИГУРАЦИЯ ====================
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]
CAFE_ADDRESS = os.getenv("CAFE_ADDRESS", "ул. Примерная, д. 1")
CAFE_PHONE = os.getenv("CAFE_PHONE", "+7 (999) 000-00-00")
PAYMENT_CARD = os.getenv("PAYMENT_CARD", "2200 1111 2222 3333")
CAFE_LAT = float(os.getenv("CAFE_LAT", "55.7558"))
CAFE_LON = float(os.getenv("CAFE_LON", "37.6173"))

# Настройки лояльности
LOYALTY_BRONZE_THRESHOLD = 5000
LOYALTY_SILVER_THRESHOLD = 15000
LOYALTY_GOLD_THRESHOLD = 50000
LOYALTY_CASHBACK_BRONZE = 0.03
LOYALTY_CASHBACK_SILVER = 0.05
LOYALTY_CASHBACK_GOLD = 0.10
REFERRAL_BONUS = 500

# Настройки кухни
KITCHEN_CAPACITY_PER_HOUR = 10  # макс заказов в час
PREP_TIME_BASE = 40  # базовое время приготовления в минутах
PREP_TIME_PER_ITEM = 10  # доп время за каждое блюдо

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

# ==================== MIDDLEWARE ДЛЯ ОБРАБОТКИ ОШИБОК ====================

@dp.errors()
async def errors_handler(exception, update, router):
    """Глобальный обработчик ошибок"""
    logging.error(f"Ошибка в обновлении {update}: {exception}", exc_info=True)
    
    # Попытаемся получить user_id из обновления
    user_id = None
    if hasattr(update, 'message') and update.message:
        user_id = update.message.from_user.id
    elif hasattr(update, 'callback_query') and update.callback_query:
        user_id = update.callback_query.from_user.id
    
    # Уведомляем админа об ошибке
    if user_id and ADMIN_IDS:
        try:
            for admin_id in ADMIN_IDS:
                await bot.send_message(
                    admin_id,
                    f"🚨 <b>Ошибка в боте</b>\n\n"
                    f"Пользователь: {user_id}\n"
                    f"Тип: {type(exception).__name__}\n"
                    f"Сообщение: {str(exception)[:500]}",
                    parse_mode=ParseMode.HTML
                )
        except Exception as e:
            logging.error(f"Не удалось уведомить админа об ошибке: {e}")
    
    return True  # Ошибка обработана

# ==================== ENUMS И КЛАССЫ ====================

class OrderPriority(Enum):
    NORMAL = "normal"
    VIP = "vip"
    PREORDER = "preorder"

class OrderStatus(Enum):
    NEW = "new"
    ACCEPTED = "accepted"
    PREP = "prep"  # заготовка
    COOKING = "cooking"
    ASSEMBLY = "assembly"  # сборка
    READY = "ready"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class LoyaltyLevel(Enum):
    NONE = "none"
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"

class DietType(Enum):
    NONE = "none"
    VEGAN = "vegan"
    VEGETARIAN = "vegetarian"
    GLUTEN_FREE = "gluten_free"
    DAIRY_FREE = "dairy_free"
    NUT_FREE = "nut_free"
    KETO = "keto"

@dataclass
class KitchenTimer:
    order_id: int
    stage: str
    start_time: datetime
    estimated_end: datetime
    actual_end: Optional[datetime] = None

@dataclass
class DeliveryZone:
    name: str
    min_order: int
    delivery_cost: int
    free_from: int
    polygon: List[Tuple[float, float]]  # координаты зоны

# ==================== БАЗА ДАННЫХ ====================

DB_NAME = 'cafe_ecosystem.db'

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Пользователи с расширенными полями
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                phone TEXT,
                email TEXT,
                birth_date TEXT,
                diet_type TEXT DEFAULT 'none',
                allergens TEXT,  -- JSON список
                registered_at TEXT,
                last_order_at TEXT,
                total_spent INTEGER DEFAULT 0,
                loyalty_points INTEGER DEFAULT 0,
                loyalty_level TEXT DEFAULT 'none',
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                is_verified INTEGER DEFAULT 0,
                favorite_dishes TEXT,  -- JSON список
                order_history_stats TEXT  -- JSON для ML
            )
        ''')
        
        # Меню с аллергенами и диетами
        await db.execute('''
            CREATE TABLE IF NOT EXISTS menu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                price INTEGER,
                cost_price INTEGER,  -- себестоимость
                image_url TEXT,
                is_active INTEGER DEFAULT 1,
                category TEXT,
                prep_time INTEGER,  -- время приготовления в минутах
                complexity INTEGER DEFAULT 1,  -- 1-5 сложность
                allergens TEXT,  -- JSON список аллергенов
                diet_tags TEXT,  -- JSON список диет
                ingredients TEXT,  -- JSON для калькуляции
                popularity_score INTEGER DEFAULT 0,
                rating REAL DEFAULT 5.0,
                total_reviews INTEGER DEFAULT 0
            )
        ''')
        
        # Заказы с приоритетами и таймерами
        await db.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                items TEXT,  -- JSON с деталями
                address TEXT,
                lat REAL,
                lon REAL,
                delivery_zone TEXT,
                delivery_time TEXT,
                priority TEXT DEFAULT 'normal',
                total_price INTEGER,
                discount_applied INTEGER DEFAULT 0,
                points_earned INTEGER,
                points_spent INTEGER DEFAULT 0,
                promo_code TEXT,
                status TEXT DEFAULT 'new',
                current_stage TEXT,  -- текущий этап приготовления
                estimated_ready_time TEXT,
                actual_ready_time TEXT,
                courier_id INTEGER,
                created_at TEXT,
                updated_at TEXT,
                review_requested INTEGER DEFAULT 0
            )
        ''')
        
        # Таймеры кухни
        await db.execute('''
            CREATE TABLE IF NOT EXISTS kitchen_timers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                stage TEXT,
                start_time TEXT,
                estimated_end TEXT,
                actual_end TEXT,
                is_completed INTEGER DEFAULT 0
            )
        ''')
        
        # Загрузка кухни
        await db.execute('''
            CREATE TABLE IF NOT EXISTS kitchen_load (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                hour INTEGER,
                max_capacity INTEGER,
                current_load INTEGER DEFAULT 0,
                is_blocked INTEGER DEFAULT 0
            )
        ''')
        
        # Корзина
        await db.execute('''
            CREATE TABLE IF NOT EXISTS cart (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                dish_id INTEGER,
                dish_name TEXT,
                ingredients TEXT,
                extra_price INTEGER,
                base_price INTEGER,
                added_at TEXT
            )
        ''')
        
        # Промокоды
        await db.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                type TEXT,  -- percent, fixed, free_delivery
                value INTEGER,
                min_order INTEGER DEFAULT 0,
                max_uses INTEGER,
                used_count INTEGER DEFAULT 0,
                valid_from TEXT,
                valid_until TEXT,
                applicable_users TEXT,  -- JSON список или all
                created_by INTEGER
            )
        ''')
        
        # Отзывы
        await db.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                user_id INTEGER,
                rating INTEGER,
                text TEXT,
                sentiment_score REAL,  -- AI анализ тональности
                categories TEXT,  -- JSON: еда, сервис, доставка
                created_at TEXT,
                is_published INTEGER DEFAULT 1,
                admin_reply TEXT
            )
        ''')
        
        # Аналитика
        await db.execute('''
            CREATE TABLE IF NOT EXISTS analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                hour INTEGER,
                metric_type TEXT,
                metric_value REAL,
                details TEXT  -- JSON
            )
        ''')
        
        # События для прогнозирования
        await db.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                event_type TEXT,  -- holiday, weather, promotion
                description TEXT,
                impact_factor REAL  -- коэффициент влияния на спрос
            )
        ''')
        
        # Курьеры
        await db.execute('''
            CREATE TABLE IF NOT EXISTS couriers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                phone TEXT,
                status TEXT DEFAULT 'offline',  -- offline, online, busy
                current_lat REAL,
                current_lon REAL,
                last_update TEXT
            )
        ''')
        
        # Зоны доставки
        await db.execute('''
            CREATE TABLE IF NOT EXISTS delivery_zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                min_order INTEGER,
                delivery_cost INTEGER,
                free_from INTEGER,
                polygon TEXT,  -- JSON координаты
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # Подписчики и рассылки
        await db.execute('''
            CREATE TABLE IF NOT EXISTS subscribers (
                user_id INTEGER PRIMARY KEY,
                is_active INTEGER DEFAULT 1,
                email_consent INTEGER DEFAULT 0,
                sms_consent INTEGER DEFAULT 0,
                push_consent INTEGER DEFAULT 1,
                unsubscribed_at TEXT
            )
        ''')
        
        # Блюдо дня
        await db.execute('''
            CREATE TABLE IF NOT EXISTS dish_of_day (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dish_id INTEGER,
                special_price INTEGER,
                date TEXT,
                orders_count INTEGER DEFAULT 0
            )
        ''')
        
        # AB тесты
        await db.execute('''
            CREATE TABLE IF NOT EXISTS ab_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT,
                variant_a TEXT,
                variant_b TEXT,
                user_segment TEXT,
                start_date TEXT,
                end_date TEXT,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # История баллов лояльности
        await db.execute('''
            CREATE TABLE IF NOT EXISTS points_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                type TEXT,
                order_id INTEGER,
                created_at TEXT
            )
        ''')
        
        await db.commit()
        logging.info("✅ База данных инициализирована")

# ==================== СИСТЕМА ЛОЯЛЬНОСТИ ====================

class LoyaltySystem:
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
        return f"CAFE{user_id}{hashlib.md5(str(user_id).encode()).hexdigest()[:4].upper()}"

class LoyaltyManager:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db
    
    async def get_user_stats(self, user_id: int) -> Dict:
        cursor = await self.db.execute(
            "SELECT total_spent, loyalty_points, loyalty_level, referral_code, referred_by FROM users WHERE user_id = ?",
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
    
    def _get_level_name(self, level: LoyaltyLevel) -> str:
        return {
            LoyaltyLevel.NONE: "🆕 Новичок",
            LoyaltyLevel.BRONZE: "🥉 Бронза",
            LoyaltyLevel.SILVER: "🥈 Серебро",
            LoyaltyLevel.GOLD: "🥇 Золото"
        }.get(level, "Неизвестно")
    
    async def add_points(self, user_id: int, amount: int, order_id: int = None):
        await self.db.execute(
            "UPDATE users SET loyalty_points = loyalty_points + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await self.db.execute(
            "INSERT INTO points_history (user_id, amount, type, order_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, "earn", order_id, datetime.now().isoformat())
        )
        await self.db.commit()
    
    async def spend_points(self, user_id: int, amount: int, order_id: int) -> bool:
        cursor = await self.db.execute(
            "SELECT loyalty_points FROM users WHERE user_id = ?", (user_id,)
        )
        current = (await cursor.fetchone())[0]
        
        if current < amount:
            return False
        
        await self.db.execute(
            "UPDATE users SET loyalty_points = loyalty_points - ? WHERE user_id = ?",
            (amount, user_id)
        )
        await self.db.execute(
            "INSERT INTO points_history (user_id, amount, type, order_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, -amount, "spend", order_id, datetime.now().isoformat())
        )
        await self.db.commit()
        return True
    
    async def process_referral(self, new_user_id: int, referral_code: str):
        cursor = await self.db.execute(
            "SELECT user_id FROM users WHERE referral_code = ?", (referral_code,)
        )
        referrer = await cursor.fetchone()
        
        if not referrer or referrer[0] == new_user_id:
            return False
        
        # Начисляем бонусы
        await self.add_points(referrer[0], REFERRAL_BONUS)
        await self.db.execute(
            "UPDATE users SET referred_by = ? WHERE user_id = ?",
            (referrer[0], new_user_id)
        )
        await self.db.commit()
        
        # Уведомляем реферера
        try:
            await bot.send_message(
                referrer[0],
                f"🎉 У вас новый реферал! Начислено {REFERRAL_BONUS} баллов."
            )
        except:
            pass
        
        return True
    
    async def check_birthday(self, user_id: int) -> Optional[int]:
        cursor = await self.db.execute(
            "SELECT birth_date FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        
        if not row or not row[0]:
            return None
        
        birth = datetime.strptime(row[0], "%d.%m.%Y")
        today = datetime.now()
        
        if birth.day == today.day and birth.month == today.month:
            return 15  # 15% скидка в ДР
        return None

# ==================== СИСТЕМА ТАЙМЕРОВ КУХНИ ====================

class KitchenTimerManager:
    STAGES = {
        'prep': ('🔪 Заготовка', 10),
        'cooking': ('👨‍🍳 Приготовление', 20),
        'assembly': ('📦 Сборка', 5),
        'packing': ('🥡 Упаковка', 3)
    }
    
    def __init__(self, db: aiosqlite.Connection):
        self.db = db
        self.active_timers: Dict[int, List[KitchenTimer]] = {}
    
    def calculate_prep_time(self, items: List[Dict], priority: OrderPriority) -> int:
        """Расчет времени приготовления с учетом сложности"""
        base_time = PREP_TIME_BASE
        total_complexity = sum(item.get('complexity', 1) for item in items)
        
        # Время за количество и сложность
        cooking_time = sum(
            item.get('prep_time', PREP_TIME_PER_ITEM) * item.get('complexity', 1)
            for item in items
        )
        
        total = base_time + cooking_time
        
        # VIP заказы в приоритете (-20% времени)
        if priority == OrderPriority.VIP:
            total = int(total * 0.8)
        
        # Предзаказы могут быть дольше
        if priority == OrderPriority.PREORDER:
            total = int(total * 1.2)
        
        return max(15, total)  # минимум 15 минут
    
    async def start_order_timer(self, order_id: int, items: List[Dict], priority: OrderPriority):
        """Запуск многоэтапных таймеров"""
        total_time = self.calculate_prep_time(items, priority)
        
        # Распределяем время по этапам пропорционально
        stage_weights = {'prep': 0.2, 'cooking': 0.5, 'assembly': 0.2, 'packing': 0.1}
        
        current_time = datetime.now()
        timers = []
        
        for stage, (name, base_minutes) in self.STAGES.items():
            stage_time = int(total_time * stage_weights[stage])
            estimated_end = current_time + timedelta(minutes=stage_time)
            
            await self.db.execute(
                """INSERT INTO kitchen_timers 
                   (order_id, stage, start_time, estimated_end) 
                   VALUES (?, ?, ?, ?)""",
                (order_id, stage, current_time.isoformat(), estimated_end.isoformat())
            )
            
            timers.append(KitchenTimer(
                order_id=order_id,
                stage=stage,
                start_time=current_time,
                estimated_end=estimated_end
            ))
            
            current_time = estimated_end
        
        await self.db.commit()
        self.active_timers[order_id] = timers
        
        # Запускаем фоновый мониторинг
        asyncio.create_task(self._monitor_order(order_id))
    
    async def _monitor_order(self, order_id: int):
        """Мониторинг прогресса заказа"""
        for stage_name, (stage_label, _) in self.STAGES.items():
            # Ждем завершения этапа (в реальности тут интеграция с кухонным дисплеем)
            await asyncio.sleep(60)  # имитация
            
            await self.db.execute(
                """UPDATE kitchen_timers SET is_completed = 1, actual_end = ? 
                   WHERE order_id = ? AND stage = ?""",
                (datetime.now().isoformat(), order_id, stage_name)
            )
            await self.db.commit()
            
            # Уведомляем клиента о переходе этапа
            await self._notify_stage_change(order_id, stage_name)
            
            # Обновляем статус заказа
            if stage_name == 'prep':
                await self._update_order_status(order_id, OrderStatus.COOKING)
            elif stage_name == 'cooking':
                await self._update_order_status(order_id, OrderStatus.ASSEMBLY)
            elif stage_name == 'assembly':
                await self._update_order_status(order_id, OrderStatus.READY)
    
    async def _notify_stage_change(self, order_id: int, stage: str):
        cursor = await self.db.execute(
            "SELECT user_id FROM orders WHERE id = ?", (order_id,)
        )
        user_id = (await cursor.fetchone())[0]
        
        stage_messages = {
            'prep': "🔪 Начинаем заготовку ингредиентов...",
            'cooking': "👨‍🍳 Ваш заказ готовится на кухне!",
            'assembly': "📦 Собираем ваш заказ...",
            'packing': "🥡 Упаковываем для доставки!"
        }
        
        try:
            await bot.send_message(user_id, stage_messages.get(stage, ""))
        except:
            pass
    
    async def _update_order_status(self, order_id: int, status: OrderStatus):
        await self.db.execute(
            "UPDATE orders SET status = ?, current_stage = ?, updated_at = ? WHERE id = ?",
            (status.value, status.value, datetime.now().isoformat(), order_id)
        )
        await self.db.commit()

# ==================== УПРАВЛЕНИЕ ЗАГРУЗКОЙ ====================

class KitchenLoadManager:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db
    
    async def check_capacity(self, delivery_time: datetime) -> Tuple[bool, int]:
        """Проверка доступности слота"""
        date_str = delivery_time.strftime("%Y-%m-%d")
        hour = delivery_time.hour
        
        cursor = await self.db.execute(
            """SELECT current_load, max_capacity, is_blocked 
               FROM kitchen_load WHERE date = ? AND hour = ?""",
            (date_str, hour)
        )
        row = await cursor.fetchone()
        
        if not row:
            # Создаем запись если нет
            await self.db.execute(
                "INSERT INTO kitchen_load (date, hour, max_capacity) VALUES (?, ?, ?)",
                (date_str, hour, KITCHEN_CAPACITY_PER_HOUR)
            )
            await self.db.commit()
            return True, KITCHEN_CAPACITY_PER_HOUR
        
        current_load, max_capacity, is_blocked = row
        
        if is_blocked:
            return False, 0
        
        available = max_capacity - current_load
        return available > 0, available
    
    async def reserve_slot(self, delivery_time: datetime, order_id: int) -> bool:
        """Бронирование слота"""
        can_reserve, _ = await self.check_capacity(delivery_time)
        
        if not can_reserve:
            return False
        
        date_str = delivery_time.strftime("%Y-%m-%d")
        hour = delivery_time.hour
        
        await self.db.execute(
            """UPDATE kitchen_load 
               SET current_load = current_load + 1 
               WHERE date = ? AND hour = ?""",
            (date_str, hour)
        )
        await self.db.commit()
        return True
    
    async def release_slot(self, delivery_time: datetime):
        """Освобождение слота при отмене"""
        date_str = delivery_time.strftime("%Y-%m-%d")
        hour = delivery_time.hour
        
        await self.db.execute(
            """UPDATE kitchen_load 
               SET current_load = MAX(0, current_load - 1) 
               WHERE date = ? AND hour = ?""",
            (date_str, hour)
        )
        await self.db.commit()
    
    async def get_available_slots(self, date: datetime.date) -> List[int]:
        """Получение доступных слотов на дату"""
        date_str = date.strftime("%Y-%m-%d")
        slots = []
        
        for hour in range(10, 23):  # 10:00 - 22:00
            can_reserve, available = await self.check_capacity(
                datetime.combine(date, dt_time(hour))
            )
            if can_reserve:
                slots.append(hour)
        
        return slots
    
    async def block_slot(self, date: datetime.date, hour: int, reason: str = ""):
        """Блокировка слота админом"""
        date_str = date.strftime("%Y-%m-%d")
        await self.db.execute(
            """INSERT OR REPLACE INTO kitchen_load 
               (date, hour, max_capacity, is_blocked) VALUES (?, ?, ?, 1)""",
            (date_str, hour, 0)
        )
        await self.db.commit()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ КОРЗИНЫ ====================

async def get_cart_count(user_id: int) -> int:
    """Получить количество товаров в корзине пользователя"""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM cart WHERE user_id = ?",
            (user_id,)
        )
        count = (await cursor.fetchone())[0]
        return count

async def show_cart(callback: types.CallbackQuery, state: FSMContext):
    """Отображение содержимого корзины"""
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, dish_id, dish_name, base_price, extra_price, ingredients FROM cart WHERE user_id = ?",
            (user_id,)
        )
        cart_items = await cursor.fetchall()

    if not cart_items:
        builder = InlineKeyboardBuilder()
        builder.button(text="🍽️ Перейти в меню", callback_data="menu")
        builder.button(text="🔙 Назад", callback_data="back_to_main")
        builder.adjust(1)

        await callback.message.edit_text(
            "🛒 <b>Корзина пуста</b>\n\nДобавьте что-нибудь вкусное!",
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
        return

    subtotal = 0
    text = "🛒 <b>Ваш заказ</b>\n\n"

    for item in cart_items:
        item_id, dish_id, dish_name, base_price, extra_price, ingredients = item
        item_total = base_price + extra_price
        subtotal += item_total

        text += f"• <b>{dish_name}</b> — {base_price}₽"
        if extra_price > 0:
            text += f" (+{extra_price}₽ доп.)"
        text += f"\n  Итого: {item_total}₽\n\n"

    # Расчет доставки (по умолчанию)
    delivery_cost = 199  # базовая стоимость
    free_delivery_from = 1500
    if subtotal >= free_delivery_from:
        delivery_cost = 0
        text += f"🚚 Доставка: <b>бесплатно</b> (от {free_delivery_from}₽)\n\n"
    else:
        text += f"🚚 Доставка: {delivery_cost}₽\n"
        text += f"(Бесплатно от {free_delivery_from}₽)\n\n"

    total = subtotal + delivery_cost

    text += f"💰 <b>Итого: {total}₽</b>\n"
    text += f"   Товары: {subtotal}₽\n"
    text += f"   Доставка: {delivery_cost}₽\n"

    # Проверяем баллы
    cursor = await db.execute(
        "SELECT loyalty_points FROM users WHERE user_id = ?",
        (user_id,)
    )
    points_row = await cursor.fetchone()
    points = points_row[0] if points_row else 0

    builder = InlineKeyboardBuilder()

    if points > 0:
        max_points_use = min(points, int(subtotal * 0.3))  # максимум 30% от суммы
        if max_points_use > 0:
            builder.button(
                text=f"🎯 Использовать баллы (до {max_points_use})",
                callback_data=f"use_points_{max_points_use}"
            )

    builder.button(text="🎁 Промокод", callback_data="enter_promo_order")
    builder.button(text="📝 Оформить заказ", callback_data="checkout")
    builder.button(text="🗑️ Очистить корзину", callback_data="clear_cart")
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    builder.adjust(1)

    await state.update_data(
        cart_items=cart_items,
        subtotal=subtotal,
        delivery_cost=delivery_cost,
        total=total,
        points_available=points
    )

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

async def show_order_summary(callback: types.CallbackQuery, state: FSMContext):
    """Отображение сводки заказа перед оплатой"""
    user_id = callback.from_user.id
    data = await state.get_data()

    subtotal = data.get('subtotal', 0)
    delivery_cost = data.get('delivery_cost', 0)
    promo_discount = data.get('promo_discount', 0)
    points_used = data.get('points_used', 0)

    total = max(0, subtotal + delivery_cost - promo_discount - points_used)

    await state.update_data(total=total)

    text = "📋 <b>Сводка заказа</b>\n\n"
    text += f"🛒 Товары: {subtotal}₽\n"
    text += f"🚚 Доставка: {delivery_cost if delivery_cost > 0 else 0}₽\n"

    if promo_discount > 0:
        text += f"🎁 Скидка по промокоду: -{promo_discount}₽\n"

    if points_used > 0:
        text += f"🎯 Списано баллов: -{points_used}\n"

    text += f"\n💰 <b>Итого к оплате: {total}₽</b>"

    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Оплатить", callback_data="pay_order")
    builder.button(text="🔙 Назад к корзине", callback_data="cart")
    builder.button(text="❌ Отмена", callback_data="cancel_order")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

async def checkout(callback: types.CallbackQuery, state: FSMContext):
    """Начало процесса оформления заказа"""
    user_id = callback.from_user.id

    # Проверяем корзину
    cart_count = await get_cart_count(user_id)
    if cart_count == 0:
        await callback.answer("Корзина пуста!", show_alert=True)
        return

    # Запрашиваем адрес доставки
    text = (
        "📍 <b>Адрес доставки</b>\n\n"
        "Введите адрес доставки в формате:\n"
        "<i>ул. Примерная, д. 1, кв. 10</i>\n\n"
        "Или отправьте геолокацию 📍"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад к корзине", callback_data="cart")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await state.set_state(OrderState.entering_address)

# ==================== ДОСТАВКА И ЗОНЫ ====================

class DeliveryManager:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db
    
    def calculate_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Haversine formula для расстояния в км"""
        R = 6371  # радиус Земли в км
        
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)
        
        a = math.sin(delta_lat/2)**2 + \
            math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        
        return R * c
    
    def is_point_in_zone(self, lat: float, lon: float, polygon: List[Tuple[float, float]]) -> bool:
        """Ray casting algorithm для проверки точки в полигоне"""
        n = len(polygon)
        inside = False
        
        p1x, p1y = polygon[0]
        for i in range(n + 1):
            p2x, p2y = polygon[i % n]
            if lon > min(p1y, p2y):
                if lon <= max(p1y, p2y):
                    if lat <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (lon - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or lat <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        
        return inside
    
    async def get_zone_for_address(self, lat: float, lon: float) -> Optional[Dict]:
        """Определение зоны доставки по координатам"""
        cursor = await self.db.execute(
            "SELECT * FROM delivery_zones WHERE is_active = 1"
        )
        zones = await cursor.fetchall()
        
        for zone in zones:
            polygon = json.loads(zone[5])  # polygon column
            if self.is_point_in_zone(lat, lon, polygon):
                return {
                    'id': zone[0],
                    'name': zone[1],
                    'min_order': zone[2],
                    'delivery_cost': zone[3],
                    'free_from': zone[4]
                }
        
        return None
    
    async def calculate_delivery_cost(self, lat: float, lon: float, order_sum: int) -> Dict:
        """Расчет стоимости доставки"""
        zone = await self.get_zone_for_address(lat, lon)
        
        if not zone:
            # Зона не найдена — доставка невозможна или по умолчанию
            return {
                'available': False,
                'reason': 'Адрес вне зоны доставки'
            }
        
        if order_sum < zone['min_order']:
            return {
                'available': False,
                'reason': f'Минимальная сумма заказа: {zone["min_order"]}₽'
            }
        
        cost = 0 if order_sum >= zone['free_from'] else zone['delivery_cost']
        
        return {
            'available': True,
            'zone_name': zone['name'],
            'cost': cost,
            'free_from': zone['free_from'],
            'min_order': zone['min_order']
        }
    
    async def find_nearest_courier(self, lat: float, lon: float) -> Optional[int]:
        """Поиск ближайшего свободного курьера"""
        cursor = await self.db.execute(
            """SELECT id, current_lat, current_lon 
               FROM couriers 
               WHERE status = 'online' 
               AND last_update > datetime('now', '-5 minutes')"""
        )
        couriers = await cursor.fetchall()
        
        if not couriers:
            return None
        
        min_distance = float('inf')
        nearest_id = None
        
        for courier in couriers:
            dist = self.calculate_distance(lat, lon, courier[1], courier[2])
            if dist < min_distance:
                min_distance = dist
                nearest_id = courier[0]
        
        return nearest_id

# ==================== ML РЕКОМЕНДАЦИИ ====================

class MLRecommendationEngine:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db
    
    async def get_recommendations(self, user_id: int, limit: int = 5) -> List[Dict]:
        """Персональные рекомендации на основе истории"""
        # Получаем историю заказов пользователя
        cursor = await self.db.execute(
            "SELECT items FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
            (user_id,)
        )
        orders = await cursor.fetchall()
        
        if not orders:
            # Новый пользователь — популярные блюда
            return await self._get_popular_dishes(limit)
        
        # Анализируем предпочтения
        category_counts = {}
        dish_counts = {}
        
        for order in orders:
            items = json.loads(order[0])
            for item in items:
                dish_id = item.get('dish_id')
                category = item.get('category', 'unknown')
                
                category_counts[category] = category_counts.get(category, 0) + 1
                dish_counts[dish_id] = dish_counts.get(dish_id, 0) + 1
        
        # Находим похожие блюда
        favorite_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:2]
        favorite_categories = [cat[0] for cat in favorite_categories]
        
        # Исключаем уже часто заказываемые
        excluded_dishes = list(dish_counts.keys())
        
        # Запрос рекомендаций
        if favorite_categories:
            placeholders = ','.join('?' * len(excluded_dishes)) if excluded_dishes else '0'
            query = f"""
                SELECT * FROM menu 
                WHERE category IN ({','.join('?' * len(favorite_categories))})
                AND id NOT IN ({placeholders})
                AND is_active = 1
                ORDER BY popularity_score DESC, rating DESC
                LIMIT ?
            """
            params = favorite_categories + (excluded_dishes if excluded_dishes else []) + [limit]
        else:
            return await self._get_popular_dishes(limit)
        
        cursor = await self.db.execute(query, params)
        dishes = await cursor.fetchall()
        
        return [self._dish_to_dict(dish) for dish in dishes]
    
    async def _get_popular_dishes(self, limit: int) -> List[Dict]:
        cursor = await self.db.execute(
            """SELECT * FROM menu 
               WHERE is_active = 1 
               ORDER BY popularity_score DESC, rating DESC 
               LIMIT ?""",
            (limit,)
        )
        dishes = await cursor.fetchall()
        return [self._dish_to_dict(dish) for dish in dishes]
    
    def _dish_to_dict(self, dish: tuple) -> Dict:
        return {
            'id': dish[0],
            'name': dish[1],
            'description': dish[2],
            'price': dish[3],
            'category': dish[6],
            'rating': dish[12],
            'diet_tags': json.loads(dish[10]) if dish[10] else []
        }
    
    async def predict_demand(self, target_date: datetime.date) -> Dict[str, int]:
        """Прогноз спроса на основе истории и событий"""
        weekday = target_date.weekday()
        
        # Средние значения по дням недели
        cursor = await self.db.execute(
            """SELECT AVG(metric_value) FROM analytics 
               WHERE metric_type = 'orders_count' 
               AND strftime('%w', date) = ?""",
            (str(weekday),)
        )
        avg_orders = (await cursor.fetchone())[0] or 50
        
        # Коэффициент событий
        cursor = await self.db.execute(
            "SELECT SUM(impact_factor) FROM events WHERE date = ?",
            (target_date.isoformat(),)
        )
        event_factor = (await cursor.fetchone())[0] or 1.0
        
        # Погода (имитация)
        weather_factor = 1.0  # В реальности — интеграция с API погоды
        
        prediction = int(avg_orders * event_factor * weather_factor)
        
        # По категориям
        categories = ['pizza', 'burger', 'salad', 'pasta', 'drinks']
        distribution = {
            'pizza': 0.3,
            'burger': 0.25,
            'salad': 0.15,
            'pasta': 0.2,
            'drinks': 0.1
        }
        
        return {
            'total': prediction,
            'by_category': {cat: int(prediction * dist) for cat, dist in distribution.items()}
        }

# ==================== АНАЛИТИКА ====================

class AnalyticsManager:
    def __init__(self, db: aiosqlite.Connection):
        self.db = db
    
    async def log_event(self, metric_type: str, value: float, details: Dict = None):
        now = datetime.now()
        await self.db.execute(
            """INSERT INTO analytics (date, hour, metric_type, metric_value, details) 
               VALUES (?, ?, ?, ?, ?)""",
            (
                now.strftime("%Y-%m-%d"),
                now.hour,
                metric_type,
                value,
                json.dumps(details) if details else None
            )
        )
        await self.db.commit()
    
    async def get_dashboard_data(self) -> Dict:
        """Real-time данные для дашборда"""
        today = datetime.now().strftime("%Y-%m-%d")
        current_hour = datetime.now().hour
        
        # Заказы сегодня
        cursor = await self.db.execute(
            "SELECT COUNT(*), SUM(total_price) FROM orders WHERE DATE(created_at) = ?",
            (today,)
        )
        today_orders, today_revenue = await cursor.fetchone()
        
        # В работе
        cursor = await self.db.execute(
            """SELECT COUNT(*) FROM orders 
               WHERE status IN ('new', 'accepted', 'cooking', 'prep', 'assembly')"""
        )
        in_progress = (await cursor.fetchone())[0]
        
        # Среднее время приготовления сегодня
        cursor = await self.db.execute(
            """SELECT AVG(
                (julianday(actual_ready_time) - julianday(created_at)) * 24 * 60
            ) FROM orders 
            WHERE DATE(created_at) = ? AND actual_ready_time IS NOT NULL""",
            (today,)
        )
        avg_prep_time = (await cursor.fetchone())[0] or 0
        
        # По часам
        cursor = await self.db.execute(
            """SELECT hour, SUM(metric_value) FROM analytics 
               WHERE date = ? AND metric_type = 'revenue'
               GROUP BY hour ORDER BY hour""",
            (today,)
        )
        hourly_revenue = await cursor.fetchall()
        
        # Топ блюда
        cursor = await self.db.execute(
            """SELECT items FROM orders WHERE DATE(created_at) = ?""",
            (today,)
        )
        all_items = await cursor.fetchall()
        
        dish_counts = {}
        for order_items in all_items:
            items = json.loads(order_items[0])
            for item in items:
                name = item.get('dish_name', 'Unknown')
                dish_counts[name] = dish_counts.get(name, 0) + 1
        
        top_dishes = sorted(dish_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            'today_orders': today_orders or 0,
            'today_revenue': today_revenue or 0,
            'in_progress': in_progress,
            'avg_prep_time': round(avg_prep_time, 1),
            'hourly_revenue': hourly_revenue,
            'top_dishes': top_dishes,
            'kitchen_load': await self._get_current_kitchen_load()
        }
    
    async def _get_current_kitchen_load(self) -> Dict:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        hour = now.hour
        
        cursor = await self.db.execute(
            "SELECT current_load, max_capacity FROM kitchen_load WHERE date = ? AND hour = ?",
            (date_str, hour)
        )
        row = await cursor.fetchone()
        
        if not row:
            return {'current': 0, 'max': KITCHEN_CAPACITY_PER_HOUR, 'percent': 0}
        
        current, max_cap = row
        return {
            'current': current,
            'max': max_cap,
            'percent': int((current / max_cap) * 100) if max_cap > 0 else 0
        }

# ==================== ОСНОВНЫЕ КЛАВИАТУРЫ ====================

def get_main_menu_keyboard(is_admin: bool = False, has_cart: bool = False):
    builder = InlineKeyboardBuilder()
    builder.button(text="🍽️ Меню", callback_data="menu")
    if has_cart:
        builder.button(text="🛒 Корзина", callback_data="cart")
    builder.button(text="⭐ Избранное", callback_data="favorites")
    builder.button(text="🤖 Рекомендации", callback_data="recommendations")
    builder.button(text="🍲 Блюдо дня", callback_data="dish_of_day")
    builder.button(text="📦 Мои заказы", callback_data="my_orders")
    builder.button(text="💎 Баллы", callback_data="loyalty")
    builder.button(text="👤 Профиль", callback_data="profile")
    builder.button(text="📍 Адрес кафе", callback_data="cafe_info")
    if is_admin:
        builder.button(text="🔧 Админ панель", callback_data="admin_panel")
    builder.adjust(2)
    return builder.as_markup()

def get_diet_filter_keyboard(selected: List[str] = None):
    if selected is None:
        selected = []
    
    builder = InlineKeyboardBuilder()
    diets = [
        ('vegan', '🌱 Веган'),
        ('vegetarian', '🥗 Вегетарианец'),
        ('gluten_free', '🌾 Без глютена'),
        ('dairy_free', '🥛 Без лактозы'),
        ('nut_free', '🥜 Без орехов'),
        ('keto', '🥩 Кето')
    ]
    
    for key, label in diets:
        check = '✅ ' if key in selected else ''
        builder.button(text=f"{check}{label}", callback_data=f"diet_toggle_{key}")
    
    builder.button(text="🔍 Применить", callback_data="diet_apply")
    builder.button(text="❌ Сбросить", callback_data="diet_reset")
    builder.adjust(2)
    return builder.as_markup()

# ==================== ХЕНДЛЕРЫ (основные) ====================

class OrderState(StatesGroup):
    selecting_dish = State()
    selecting_ingredients = State()
    entering_address = State()
    selecting_delivery_type = State()
    selecting_time = State()
    selecting_date_time = State()
    confirming_order = State()
    waiting_for_payment_confirm = State()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    # Проверка реферального кода
    referral_code = None
    if message.text and len(message.text.split()) > 1:
        ref = message.text.split()[1]
        if ref.startswith("ref"):
            referral_code = ref[3:]
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Проверяем существование пользователя
        cursor = await db.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        exists = await cursor.fetchone()
        
        if not exists:
            # Новый пользователь
            ref_code = LoyaltySystem.generate_referral_code(user_id)
            
            await db.execute(
                """INSERT INTO users 
                   (user_id, username, first_name, registered_at, referral_code, referred_by) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, username, first_name, datetime.now().isoformat(), 
                 ref_code, referral_code)
            )
            await db.execute(
                "INSERT OR IGNORE INTO subscribers (user_id) VALUES (?)",
                (user_id,)
            )
            await db.commit()
            
            # Обработка реферала
            if referral_code:
                lm = LoyaltyManager(db)
                await lm.process_referral(user_id, referral_code)
            
            # Приветственные баллы
            await db.execute(
                "UPDATE users SET loyalty_points = loyalty_points + 100 WHERE user_id = ?",
                (user_id,)
            )
            await db.commit()
            
            welcome_msg = (
                f"🎉 Добро пожаловать, {first_name}!\n\n"
                f"Вам начислено 100 приветственных баллов!\n"
                f"Ваш реферальный код: <code>{ref_code}</code>\n"
                f"Приглашайте друзей и получайте по {REFERRAL_BONUS} баллов!"
            )
        else:
            welcome_msg = f"👋 С возвращением, {first_name}!"
        
        # Проверка ДР
        lm = LoyaltyManager(db)
        birthday_discount = await lm.check_birthday(user_id)
        
        if birthday_discount:
            welcome_msg += f"\n\n🎂 С Днем Рождения! Скидка {birthday_discount}% на сегодня!"
    
    is_admin = user_id in ADMIN_IDS
    cart_count = await get_cart_count(user_id)
    
    await message.answer(
        welcome_msg,
        reply_markup=get_main_menu_keyboard(is_admin, cart_count > 0),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "recommendations")
async def show_recommendations(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        ml = MLRecommendationEngine(db)
        recommendations = await ml.get_recommendations(user_id, 5)
    
    if not recommendations:
        await callback.answer("Пока нет рекомендаций", show_alert=True)
        return
    
    text = "🤖 <b>Персональные рекомендации</b>\n\n"
    for i, dish in enumerate(recommendations, 1):
        text += f"{i}. <b>{dish['name']}</b>\n"
        text += f"   ⭐ {dish['rating']} | 💰 {dish['price']}₽\n"
        if dish['diet_tags']:
            tags = ', '.join(dish['diet_tags'])
            text += f"   🏷️ {tags}\n"
        text += "\n"
    
    builder = InlineKeyboardBuilder()
    for dish in recommendations:
        builder.button(text=f"➕ {dish['name'][:20]}", callback_data=f"dish_{dish['id']}")
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "loyalty")
async def show_loyalty(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        lm = LoyaltyManager(db)
        stats = await lm.get_user_stats(user_id)
    
    if not stats:
        await callback.answer("Ошибка загрузки", show_alert=True)
        return
    
    text = (
        f"💎 <b>Программа лояльности</b>\n\n"
        f"Уровень: {stats['level_name']}\n"
        f"Кешбэк: {stats['cashback']}%\n\n"
        f"💰 Потрачено всего: {stats['total_spent']}₽\n"
        f"🎯 Баллов: {stats['points']}\n\n"
    )
    
    if stats['next_level']:
        text += (
            f"📈 До уровня {stats['next_level']}: {stats['next_threshold'] - stats['total_spent']}₽\n"
            f"Прогресс: {stats['progress']}%\n\n"
        )
    
    text += f"🔗 Ваш код: <code>{stats['referral_code']}</code>\n"
    text += f"Пригласите друга и получите {REFERRAL_BONUS} баллов!"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Использовать промокод", callback_data="enter_promo")
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "menu")
async def show_menu(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    
    # Получаем фильтры диеты из состояния
    data = await state.get_data()
    diet_filters = data.get('diet_filters', [])
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT diet_type, allergens FROM users WHERE user_id = ?",
            (user_id,)
        )
        user_prefs = await cursor.fetchone()
        
        # Базовый запрос
        query = "SELECT * FROM menu WHERE is_active = 1"
        params = []
        
        # Применяем фильтры
        if diet_filters:
            conditions = []
            for diet in diet_filters:
                conditions.append(f"diet_tags LIKE ?")
                params.append(f'%"{diet}"%')
            query += " AND (" + " OR ".join(conditions) + ")"
        
        # Исключаем аллергены пользователя
        if user_prefs and user_prefs[1]:
            allergens = json.loads(user_prefs[1])
            for allergen in allergens:
                query += " AND allergens NOT LIKE ?"
                params.append(f'%"{allergen}"%')
        
        query += " ORDER BY popularity_score DESC"
        
        cursor = await db.execute(query, params)
        dishes = await cursor.fetchall()
    
    if not dishes:
        text = "🍽️ <b>Меню</b>\n\nК сожалению, по вашим фильтрам ничего не найдено."
    else:
        text = "🍽️ <b>Наше меню</b>\n\n"
        for dish in dishes:
            diet_icons = ""
            if dish[10]:  # diet_tags
                tags = json.loads(dish[10])
                diet_icons = "".join({
                    'vegan': '🌱',
                    'vegetarian': '🥗',
                    'gluten_free': '🌾',
                    'dairy_free': '🥛',
                    'nut_free': '🥜'
                }.get(t, '') for t in tags)
            
            text += f"{diet_icons} <b>{dish[1]}</b> — {dish[3]}₽\n"
            text += f"   ⭐ {dish[12]}/5 | ⏱️ {dish[8]}мин\n\n"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔍 Фильтры", callback_data="diet_filter")
    
    for dish in dishes[:10]:  # Показываем первые 10
        builder.button(text=f"➕ {dish[1][:25]}", callback_data=f"dish_{dish[0]}")
    
    cart_count = await get_cart_count(user_id)
    if cart_count > 0:
        builder.button(text=f"🛒 Корзина ({cart_count})", callback_data="cart")
    
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "diet_filter")
async def show_diet_filter(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get('diet_filters', [])
    
    await callback.message.edit_text(
        "🔍 <b>Фильтр по диетам</b>\n\n"
        "Выберите предпочтения:",
        reply_markup=get_diet_filter_keyboard(selected),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data.startswith("diet_toggle_"))
async def toggle_diet(callback: types.CallbackQuery, state: FSMContext):
    diet = callback.data.split("_")[2]
    data = await state.get_data()
    selected = data.get('diet_filters', [])

    # Создаем копию списка для изменения
    selected = list(selected)

    if diet in selected:
        selected.remove(diet)
    else:
        selected.append(diet)

    await state.update_data(diet_filters=selected)

    # Получаем новую клавиатуру
    new_keyboard = get_diet_filter_keyboard(selected)

    # Пытаемся обновить клавиатуру, игнорируем ошибку "message is not modified"
    try:
        await callback.message.edit_reply_markup(reply_markup=new_keyboard)
    except Exception as e:
        # Игнорируем ошибку "message is not modified"
        if "message is not modified" not in str(e):
            logging.warning(f"Ошибка обновления клавиатуры диет: {e}")
    await callback.answer()

@dp.callback_query(F.data == "diet_apply")
async def apply_diet_filter(callback: types.CallbackQuery, state: FSMContext):
    await show_menu(callback, state)

@dp.callback_query(F.data == "favorites")
async def show_favorites(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT favorite_dishes FROM users WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        
        if not row or not row[0]:
            await callback.answer("У вас пока нет избранных блюд", show_alert=True)
            return
        
        favorites = json.loads(row[0])
        
        if not favorites:
            await callback.answer("У вас пока нет избранных блюд", show_alert=True)
            return
        
        # Получаем детали блюд
        placeholders = ','.join('?' * len(favorites))
        cursor = await db.execute(
            f"SELECT * FROM menu WHERE id IN ({placeholders})",
            favorites
        )
        dishes = await cursor.fetchall()
    
    text = "⭐ <b>Избранное</b>\n\n"
    builder = InlineKeyboardBuilder()
    
    for dish in dishes:
        text += f"• <b>{dish[1]}</b> — {dish[3]}₽\n"
        builder.button(text=f"🔄 Заказать {dish[1][:20]}", callback_data=f"quick_order_{dish[0]}")
    
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("quick_order_"))
async def quick_order(callback: types.CallbackQuery):
    """Быстрый повтор заказа избранного"""
    dish_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM menu WHERE id = ?", (dish_id,))
        dish = await cursor.fetchone()

        if not dish:
            await callback.answer("Блюдо не найдено", show_alert=True)
            return

        # Добавляем в корзину без ингредиентов
        await db.execute(
            """INSERT INTO cart
               (user_id, dish_id, dish_name, ingredients, extra_price, base_price, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, dish_id, dish[1], "", 0, dish[3], datetime.now().isoformat())
        )
        await db.commit()

    await callback.answer("✅ Добавлено в корзину!", show_alert=False)
    await callback.message.edit_text(
        "🛒 <b>Корзина</b>\n\n",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🍽️ В меню", callback_data="menu")
        .button(text="🔙 Назад", callback_data="back_to_main")
        .as_markup(),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "dish_of_day")
async def show_dish_of_day(callback: types.CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        today = datetime.now().strftime("%Y-%m-%d")
        cursor = await db.execute(
            """SELECT m.*, dod.special_price FROM dish_of_day dod
               JOIN menu m ON dod.dish_id = m.id
               WHERE dod.date = ?""",
            (today,)
        )
        dish = await cursor.fetchone()

        if not dish:
            await callback.answer("Сегодня блюдо дня не установлено", show_alert=True)
            return

        text = (
            f"🍲 <b>Блюдо дня!</b>\n\n"
            f"<b>{dish[1]}</b>\n"
            f"{dish[2]}\n\n"
        )

        if dish[13]:  # special_price
            text += f"💰 <s>{dish[3]}₽</s> → <b>{dish[13]}₽</b>\n"
        else:
            text += f"💰 {dish[3]}₽\n"

        text += f"⭐ {dish[12]}/5\n"
        text += f"⏱️ {dish[8]}мин"

        builder = InlineKeyboardBuilder()
        builder.button(text=f"➕ Заказать", callback_data=f"dish_{dish[0]}")
        builder.button(text="🔙 Назад", callback_data="back_to_main")

        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "my_orders")
async def show_my_orders(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """SELECT id, created_at, total_price, status
               FROM orders WHERE user_id = ?
               ORDER BY created_at DESC LIMIT 10""",
            (user_id,)
        )
        orders = await cursor.fetchall()

        if not orders:
            await callback.message.edit_text(
                "📦 <b>Мои заказы</b>\n\nУ вас пока нет заказов.",
                reply_markup=InlineKeyboardBuilder()
                .button(text="🔙 Назад", callback_data="back_to_main")
                .as_markup(),
                parse_mode=ParseMode.HTML
            )
            return

        text = "📦 <b>Мои заказы</b>\n\n"
        status_icons = {
            'new': '🆕',
            'accepted': '✅',
            'cooking': '👨‍🍳',
            'ready': '📦',
            'delivering': '🚚',
            'completed': '✔️',
            'cancelled': '❌'
        }

        for order in orders:
            order_id, created_at, total, status = order
            date = datetime.fromisoformat(created_at).strftime("%d.%m %H:%M")
            icon = status_icons.get(status, '❓')
            text += f"{icon} Заказ #{order_id} — {total}₽\n   {date}\n\n"

        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data="back_to_main")

        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "profile")
async def show_profile(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """SELECT username, first_name, phone, email, birth_date,
                      total_spent, loyalty_points, loyalty_level, referral_code
               FROM users WHERE user_id = ?""",
            (user_id,)
        )
        user = await cursor.fetchone()

        if not user:
            await callback.answer("Ошибка загрузки профиля", show_alert=True)
            return

        username, first_name, phone, email, birth_date, total_spent, points, level, ref_code = user

        text = (
            f"👤 <b>Профиль</b>\n\n"
            f"Имя: {first_name}\n"
        )
        if username:
            text += f"Username: @{username}\n"
        if phone:
            text += f"Телефон: {phone}\n"
        if email:
            text += f"Email: {email}\n"
        if birth_date:
            text += f"День рождения: {birth_date}\n"

        text += (
            f"\n💰 Потрачено: {total_spent}₽\n"
            f"🎯 Баллов: {points}\n"
            f"📊 Уровень: {level}\n"
            f"🔗 Реферальный код: <code>{ref_code}</code>"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="📝 Изменить данные", callback_data="edit_profile")
        builder.button(text="🔙 Назад", callback_data="back_to_main")

        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "edit_profile")
async def edit_profile_handler(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки редактирования профиля"""
    text = (
        "📝 <b>Редактирование профиля</b>\n\n"
        "Отправьте данные в формате:\n"
        "Телефон | Email | Дата рождения (ДД.ММ.ГГГГ)\n\n"
        "Или отправьте по одному полю:\n"
        "• Телефон: +79991234567\n"
        "• Email: example@mail.ru\n"
        "• Дата рождения: 01.01.1990\n\n"
        "Для пропуска поля напишите '-'"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="profile")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await state.set_state(OrderState.waiting_for_location)  # Используем другое состояние

@dp.message(OrderState.waiting_for_location)
async def process_edit_profile(message: types.Message, state: FSMContext):
    """Обработка данных для редактирования профиля"""
    user_id = message.from_user.id
    text = message.text.strip()

    async with aiosqlite.connect(DB_NAME) as db:
        try:
            # Проверяем формат
            if "|" in text:
                # Формат: Телефон | Email | Дата рождения
                parts = text.split("|")
                phone = parts[0].strip() if len(parts) > 0 and parts[0].strip() != "-" else None
                email = parts[1].strip() if len(parts) > 1 and parts[1].strip() != "-" else None
                birth_date = parts[2].strip() if len(parts) > 2 and parts[2].strip() != "-" else None

                if phone and phone != "-":
                    await db.execute("UPDATE users SET phone = ? WHERE user_id = ?", (phone, user_id))
                if email and email != "-":
                    await db.execute("UPDATE users SET email = ? WHERE user_id = ?", (email, user_id))
                if birth_date and birth_date != "-":
                    await db.execute("UPDATE users SET birth_date = ? WHERE user_id = ?", (birth_date, user_id))
            else:
                # Определяем тип данных
                if text.startswith("+7") or text.startswith("8"):
                    await db.execute("UPDATE users SET phone = ? WHERE user_id = ?", (text, user_id))
                elif "@" in text:
                    await db.execute("UPDATE users SET email = ? WHERE user_id = ?", (text, user_id))
                elif "." in text and len(text) == 10:
                    await db.execute("UPDATE users SET birth_date = ? WHERE user_id = ?", (text, user_id))
                else:
                    await message.answer("❌ Не удалось определить тип данных. Используйте формат: Телефон | Email | Дата рождения")
                    return

                await db.commit()

        except Exception as e:
            logging.error(f"Ошибка при обновлении профиля: {e}")
            await message.answer("❌ Произошла ошибка. Попробуйте позже.")
            return

        await db.commit()

    await message.answer("✅ Данные обновлены!")
    await state.clear()

    # Возвращаем в профиль
    builder = InlineKeyboardBuilder()
    builder.button(text="👤 Мой профиль", callback_data="profile")
    builder.button(text="🔙 В главное меню", callback_data="back_to_main")
    builder.adjust(1)
    await message.answer("🏠 Главное меню", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "cafe_info")
async def show_cafe_info(callback: types.CallbackQuery):
    text = (
        f"📍 <b>Информация о кафе</b>\n\n"
        f"📌 Адрес: {CAFE_ADDRESS}\n"
        f"📞 Телефон: {CAFE_PHONE}\n"
        f"🕐 Время работы: 10:00 - 23:00\n\n"
        f"💳 Оплата: Перевод на карту {PAYMENT_CARD}"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🗺️ Показать на карте", callback_data="show_on_map")
    builder.button(text="🔙 Назад", callback_data="back_to_main")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "show_on_map")
async def show_on_map(callback: types.CallbackQuery):
    await callback.message.answer_location(CAFE_LAT, CAFE_LON)
    await callback.answer()

@dp.callback_query(F.data == "diet_reset")
async def reset_diet_filter(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(diet_filters=[])
    await show_menu(callback, state)

@dp.callback_query(F.data == "cancel_order")
async def cancel_order(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Заказ отменён",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 В главное меню", callback_data="back_to_main")
        .as_markup()
    )

@dp.callback_query(F.data == "pay_order")
async def pay_order(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    total = data.get('total', 0)

    text = (
        f"💳 <b>Оплата заказа на {total}₽</b>\n\n"
        f"Переведите сумму на карту:\n"
        f"<code>{PAYMENT_CARD}</code>\n\n"
        f"После оплаты нажмите 'Подтвердить' или отправьте чек."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить оплату", callback_data="confirm_payment")
    builder.button(text="❌ Отмена", callback_data="cancel_order")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "enter_promo")
@dp.callback_query(F.data == "enter_promo_order")
async def enter_promo(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🎁 <b>Введите промокод:</b>",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Назад", callback_data="back_to_main")
        .as_markup(),
        parse_mode=ParseMode.HTML
    )
    await state.set_state(OrderState.selecting_date_time)  # Используем существующий state

@dp.message(Command("promo"))
async def cmd_promo(message: types.Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Введите промокод: /promo КОД")
        return

    promo_code = parts[1].upper()

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """SELECT type, value, min_order, max_uses, used_count, valid_until
               FROM promo_codes WHERE code = ?""",
            (promo_code,)
        )
        promo = await cursor.fetchone()

        if not promo:
            await message.answer("❌ Промокод не найден")
            return

        promo_type, value, min_order, max_uses, used_count, valid_until = promo

        # Проверка срока действия
        if valid_until:
            if datetime.now() > datetime.fromisoformat(valid_until):
                await message.answer("❌ Срок действия промокода истёк")
                return

        # Проверка лимита использований
        if max_uses and used_count >= max_uses:
            await message.answer("❌ Промокод уже использован")
            return

        promo_desc = {
            'percent': f"Скидка {value}%",
            'fixed': f"Скидка {value}₽",
            'free_delivery': "Бесплатная доставка"
        }.get(promo_type, "Скидка")

        await message.answer(f"✅ Промокод применён: {promo_desc}")

@dp.callback_query(F.data.startswith("use_points_"))
async def use_points(callback: types.CallbackQuery, state: FSMContext):
    points_to_use = int(callback.data.split("_")[2])

    await state.update_data(points_to_use=points_to_use)
    await callback.answer(f"Использовано {points_to_use} баллов", show_alert=False)
    await show_order_summary(callback, state)

@dp.callback_query(F.data.startswith("dish_"))
async def show_dish_details(callback: types.CallbackQuery):
    dish_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM menu WHERE id = ?", (dish_id,))
        dish = await cursor.fetchone()

        if not dish:
            await callback.answer("Блюдо не найдено", show_alert=True)
            return

        # Формируем описание блюда
        text = f"<b>{dish[1]}</b>\n\n{dish[2]}\n\n"
        text += f"💰 Цена: {dish[3]}₽\n"
        text += f"⭐ Рейтинг: {dish[12]}/5\n"
        text += f"⏱️ Время приготовления: {dish[8]}мин\n"

        # Аллергены и диеты
        if dish[9]: # allergens
            allergens = json.loads(dish[9])
            if allergens:
                text += f"⚠️ Аллергены: {', '.join(allergens)}\n"

        if dish[10]: # diet_tags
            tags = json.loads(dish[10])
            if tags:
                text += f"🏷️ Диеты: {', '.join(tags)}\n"

        builder = InlineKeyboardBuilder()
        builder.button(text="➕ В корзину", callback_data=f"add_to_cart_{dish_id}")
        builder.button(text="⭐ В избранное", callback_data=f"favorite_{dish_id}")
        builder.button(text="🔙 Назад", callback_data="menu")

        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("add_to_cart_"))
async def add_to_cart(callback: types.CallbackQuery, state: FSMContext):
    dish_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT name, price FROM menu WHERE id = ?", (dish_id,))
        dish = await cursor.fetchone()

        if not dish:
            await callback.answer("Блюдо не найдено", show_alert=True)
            return

        await db.execute(
            """INSERT INTO cart
            (user_id, dish_id, dish_name, ingredients, extra_price, base_price, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, dish_id, dish[0], "",0, dish[1], datetime.now().isoformat())
        )
        await db.commit()

    await callback.answer(f"✅ {dish[0]} добавлен в корзину!", show_alert=False)

    # Показываем корзину
    await show_cart(callback, state)

@dp.callback_query(F.data.startswith("favorite_"))
async def toggle_favorite(callback: types.CallbackQuery):
    dish_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT favorite_dishes FROM users WHERE user_id = ?",
            (user_id,)
        )
        row = await cursor.fetchone()

        favorites = json.loads(row[0]) if row and row[0] else []

        if dish_id in favorites:
            favorites.remove(dish_id)
            msg = "Удалено из избранного"
        else:
            favorites.append(dish_id)
            msg = "Добавлено в избранное"

        await db.execute(
            "UPDATE users SET favorite_dishes = ? WHERE user_id = ?",
            (json.dumps(favorites), user_id)
        )
        await db.commit()

    await callback.answer(msg, show_alert=False)

@dp.callback_query(F.data == "admin_orders")
async def admin_orders(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            """SELECT id, user_id, total_price, status, created_at
            FROM orders ORDER BY created_at DESC LIMIT20"""
        )
        orders = await cursor.fetchall()

        text = "📋<b>Управление заказами</b>\n\n"
        for order in orders:
            text += f"#{order[0]} | {order[1]} | {order[2]}₽ | {order[3]}\n"

        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data="admin_panel")

        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_menu")
async def admin_menu(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    text = "🍽️<b>Управление меню</b>\n\nВыберите действие:"

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить блюдо", callback_data="admin_add_dish")
    builder.button(text="📝 Редактировать", callback_data="admin_edit_dish")
    builder.button(text="❌ Удалить блюдо", callback_data="admin_delete_dish")
    builder.button(text="🔙 Назад", callback_data="admin_panel")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_couriers")
async def admin_couriers(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, name, phone, status FROM couriers")
        couriers = await cursor.fetchall()

        text = "🚚<b>Курьеры</b>\n\n"
        status_icons = {'offline': '⚫', 'online': '🟢', 'busy': '🔴'}

        for c in couriers:
            icon = status_icons.get(c[3], '❓')
            text += f"{icon} {c[1]} — {c[2]} ({c[3]})\n"

        builder = InlineKeyboardBuilder()
        builder.button(text="➕ Добавить курьера", callback_data="admin_add_courier")
        builder.button(text="🔙 Назад", callback_data="admin_panel")

        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_promo")
async def admin_promo(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT code, type, value, max_uses, used_count FROM promo_codes")
        promos = await cursor.fetchall()

        text = "🎁<b>Промокоды</b>\n\n"
        for p in promos:
            text += f"{p[0]}: {p[2]} ({p[3] - p[4]}/{p[3]})\n"

        builder = InlineKeyboardBuilder()
        builder.button(text="➕ Создать промокод", callback_data="admin_create_promo")
        builder.button(text="🔙 Назад", callback_data="admin_panel")

        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    text = "📢 <b>Рассылка сообщений</b>\n\n"
    text += "Напишите сообщение для рассылки всем подписчикам."

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_panel")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await state.set_state(OrderState.broadcasting)


@dp.message(OrderState.broadcasting)
async def process_broadcast(message: types.Message, state: FSMContext):
    """Обработка и отправка рассылки"""
    if message.from_user.id not in ADMIN_IDS:
        return

    broadcast_text = message.text

    try:
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT user_id FROM subscribers WHERE is_active = 1"
            )
            subscribers = await cursor.fetchall()

        success_count = 0
        fail_count = 0

        for (user_id,) in subscribers:
            try:
                await bot.send_message(user_id, broadcast_text)
                success_count += 1
                await asyncio.sleep(0.5)  # Задержка для избежания rate limit
            except Exception as e:
                fail_count += 1
                logging.warning(f"Не удалось отправить сообщение {user_id}: {e}")

        await message.answer(
            f"✅ Рассылка завершена!\n\n"
            f"Успешно: {success_count}\n"
            f"Ошибок: {fail_count}"
        )
    except Exception as e:
        logging.error(f"Ошибка при рассылке: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при рассылке")

    await state.clear()

@dp.callback_query(F.data == "admin_weekly_report")
async def admin_weekly_report(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    text = "📊<b>Отчёт за неделю</b>\n\n"
    text += "Здесь будет статистика за последние7 дней."

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_analytics")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("toggle_slot_"))
async def toggle_slot(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    # Извлекаем дату и час из callback_data
    parts = callback.data.split("_")
    if len(parts) >=4:
        date_str = parts[2]
        hour = int(parts[3])

        async with aiosqlite.connect(DB_NAME) as db:
            klm = KitchenLoadManager(db)
            date = datetime.strptime(date_str, "%Y-%m-%d").date()
            await klm.block_slot(date, hour)

        await callback.answer("Слот заблокирован", show_alert=False)

        await admin_kitchen_load(callback)

# ==================== НЕДОСТАЮЩИЕ ОБРАБОТЧИКИ ====================

@dp.callback_query(F.data == "cart")
async def show_cart_handler(callback: types.CallbackQuery, state: FSMContext):
    await show_cart(callback, state)

@dp.callback_query(F.data == "checkout")
async def checkout_handler(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки оформления заказа"""
    await checkout(callback, state)

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_admin = user_id in ADMIN_IDS
    cart_count = await get_cart_count(user_id)

    await callback.message.edit_text(
        "🏠 <b>Главное меню</b>",
        reply_markup=get_main_menu_keyboard(is_admin, cart_count > 0),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "clear_cart")
async def clear_cart(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
        await db.commit()

    await callback.answer("Корзина очищена", show_alert=False)
    await show_cart(callback, state)

@dp.callback_query(F.data == "confirm_payment")
async def confirm_payment(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()

    async with aiosqlite.connect(DB_NAME) as db:
        # Получаем корзину
        try:
            cursor = await db.execute(
                "SELECT dish_id, dish_name, base_price, extra_price FROM cart WHERE user_id = ?",
                (user_id,)
            )
            items = await cursor.fetchall()

            if not items:
                await callback.answer("Корзина пуста!", show_alert=True)
                return

            # Формируем JSON для заказа
            items_json = json.dumps([
                {
                    'dish_id': item[0],
                    'dish_name': item[1],
                    'base_price': item[2],
                    'extra_price': item[3]
                }
                for item in items
            ])

            total = data.get('total', 0)
            subtotal = data.get('subtotal', 0)
            delivery_cost = data.get('delivery_cost', 0)
            points_used = data.get('points_used', 0)
            promo_discount = data.get('promo_discount', 0)

            # Рассчитываем кешбэк
            lm = LoyaltyManager(db)
            user_stats = await lm.get_user_stats(user_id)
            cashback_percent = user_stats['cashback'] if user_stats else 0
            cashback = int((subtotal - promo_discount) * cashback_percent / 100)

            # Создаем заказ
            cursor = await db.execute(
                """INSERT INTO orders
                   (user_id, items, total_price, status, points_earned, points_spent, 
                    discount_applied, promo_code, delivery_time, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, items_json, total, 'new', cashback, points_used,
                 promo_discount, data.get('promo_code'),
                 data.get('delivery_time'), datetime.now().isoformat(), datetime.now().isoformat())
            )
            order_id = cursor.lastrowid

            # Списываем баллы если использовались
            if points_used > 0:
                success = await lm.spend_points(user_id, points_used, order_id)
                if not success:
                    logging.warning(f"Не удалось списать баллы пользователя {user_id}")

            # Начисляем кешбэк баллы
            if cashback > 0:
                await lm.add_points(user_id, cashback, order_id)

            # Обновляем total_spent
            await db.execute(
                "UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?",
                (subtotal - promo_discount, user_id)
            )

            # Обновляем уровень лояльности
            cursor = await db.execute("SELECT total_spent FROM users WHERE user_id = ?", (user_id,))
            total_spent = (await cursor.fetchone())[0]
            new_level = LoyaltySystem.calculate_level(total_spent).value
            await db.execute("UPDATE users SET loyalty_level = ? WHERE user_id = ?", (new_level, user_id))

            # Очищаем корзину
            await db.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
            await db.commit()

        except Exception as e:
            logging.error(f"Ошибка при создании заказа: {e}", exc_info=True)
            await callback.answer("Произошла ошибка при создании заказа. Попробуйте позже.", show_alert=True)
            return

    await state.clear()

    await callback.message.edit_text(
        f"✅ <b>Заказ принят!</b>\n\n"
        f"Номер заказа: #{order_id}\n"
        f"Сумма: {total}₽\n"
        f"Начислено баллов: {cashback}\n\n"
        f"Мы сообщим вам о готовности заказа!",
        reply_markup=get_main_menu_keyboard(user_id in ADMIN_IDS, False),
        parse_mode=ParseMode.HTML
    )

@dp.callback_query(F.data == "time_custom")
async def time_custom(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📅 <b>Выберите дату и время</b>\n\n"
        "Напишите желаемую дату и время в формате:\n"
        "ДД.ММ ЧЧ:ММ\n\n"
        "Например: 15.04 14:00",
        reply_markup=InlineKeyboardBuilder()
        .button(text="🔙 Назад", callback_data="cart")
        .as_markup(),
        parse_mode=ParseMode.HTML
    )

# ==================== ОБРАБОТЧИКИ АДМИН-ПАНЕЛИ ====================

@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    text = (
        "🔧 <b>Админ-панель</b>\n\n"
        "Выберите раздел для управления:"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Заказы", callback_data="admin_orders")
    builder.button(text="🍽️ Меню", callback_data="admin_menu")
    builder.button(text="🚚 Курьеры", callback_data="admin_couriers")
    builder.button(text="🎁 Промокоды", callback_data="admin_promo")
    builder.button(text="📊 Аналитика", callback_data="admin_analytics")
    builder.button(text="🏢 Загрузка кухни", callback_data="admin_kitchen_load")
    builder.button(text="📢 Рассылка", callback_data="admin_broadcast")
    builder.button(text="🔙 В главное меню", callback_data="back_to_main")
    builder.adjust(2)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_analytics")
async def admin_analytics(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as db:
        analytics_mgr = AnalyticsManager(db)
        dashboard = await analytics_mgr.get_dashboard_data()

    text = (
        f"📊 <b>Аналитика</b>\n\n"
        f"📦 Заказов сегодня: {dashboard['today_orders']}\n"
        f"💰 Выручка сегодня: {dashboard['today_revenue']}₽\n"
        f"👨‍🍳 В работе: {dashboard['in_progress']}\n"
        f"⏱️ Среднее время приготовления: {dashboard['avg_prep_time']} мин\n"
        f"🏢 Загрузка кухни: {dashboard['kitchen_load']['current']}/{dashboard['kitchen_load']['max']} "
        f"({dashboard['kitchen_load']['percent']}%)\n\n"
        f"🏆 Топ блюд сегодня:\n"
    )

    for i, (dish_name, count) in enumerate(dashboard['top_dishes'], 1):
        text += f"{i}. {dish_name} - {count} шт.\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="📈 Отчет за неделю", callback_data="admin_weekly_report")
    builder.button(text="🔙 Назад", callback_data="admin_panel")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_kitchen_load")
async def admin_kitchen_load(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    today = datetime.now().date()
    async with aiosqlite.connect(DB_NAME) as db:
        klm = KitchenLoadManager(db)
        available_slots = await klm.get_available_slots(today)

    text = f"🏢 <b>Загрузка кухни на {today.strftime('%d.%m.%Y')}</b>\n\n"
    text += "Доступные часы:\n"

    for hour in range(10, 23):
        if hour in available_slots:
            status = "✅"
        else:
            status = "❌"
        text += f"{status} {hour:02d}:00\n"

    text += "\nНажмите на час, чтобы заблокировать/разблокировать слот."

    builder = InlineKeyboardBuilder()
    for hour in range(10, 23):
        date_str = today.strftime("%Y-%m-%d")
        builder.button(
            text=f"{hour:02d}:00",
            callback_data=f"toggle_slot_{date_str}_{hour}"
        )
    builder.button(text="🔙 Назад", callback_data="admin_panel")
    builder.adjust(3)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_add_dish")
async def admin_add_dish(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    text = (
        "➕ <b>Добавление блюда</b>\n\n"
        "Введите данные в формате:\n"
        "Название | Описание | Цена | Категория | Время приготовления(мин)\n\n"
        "Пример:\n"
        "<i>Бургер Классик | Сочная котлета, свежие овощи | 350 | burger | 20</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_menu")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await state.set_state(OrderState.confirming_order)  # Временное состояние

@dp.message(OrderState.confirming_order)
async def process_add_dish(message: types.Message, state: FSMContext):
    parts = message.text.split("|")
    if len(parts) < 5:
        await message.answer(
            "❌ Неверный формат. Используйте: Название | Описание | Цена | Категория | Время"
        )
        return

    name = parts[0].strip()
    description = parts[1].strip()
    try:
        price = int(parts[2].strip())
        prep_time = int(parts[4].strip())
    except ValueError:
        await message.answer("❌ Цена и время должны быть числами")
        return

    category = parts[3].strip()

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """INSERT INTO menu (name, description, price, category, prep_time, is_active)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (name, description, price, category, prep_time)
        )
        await db.commit()

    await message.answer(f"✅ Блюдо '{name}' добавлено в меню!")
    await state.clear()

    # Возвращаем в админку
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В админ-панель", callback_data="admin_panel")
    builder.adjust(1)
    await message.answer("🏠 Главное меню", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_edit_dish")
async def admin_edit_dish(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, name, price, is_active FROM menu ORDER BY id DESC LIMIT 20")
        dishes = await cursor.fetchall()

    text = "📝 <b>Редактирование меню</b>\n\n"
    for dish in dishes:
        status = "✅" if dish[3] else "❌"
        text += f"{status} #{dish[0]} {dish[1]} - {dish[2]}₽\n"

    text += "\nВведите /edit ID_БЛЮДА | Новое_название | Новая_цена"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_menu")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data == "admin_delete_dish")
async def admin_delete_dish(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, name, price FROM menu WHERE is_active = 1 ORDER BY id DESC LIMIT 20")
        dishes = await cursor.fetchall()

    text = "❌ <b>Удаление блюда</b>\n\n"
    builder = InlineKeyboardBuilder()

    for dish in dishes:
        text += f"#{dish[0]} {dish[1]} - {dish[2]}₽\n"
        builder.button(text=f"🗑️ {dish[1][:20]}", callback_data=f"admin_dish_delete_{dish[0]}")

    builder.button(text="🔙 Назад", callback_data="admin_menu")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)

@dp.callback_query(F.data.startswith("admin_dish_delete_"))
async def confirm_delete_dish(callback: types.CallbackQuery):
    dish_id = int(callback.data.split("_")[3])

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT name FROM menu WHERE id = ?", (dish_id,))
        dish = await cursor.fetchone()

        if not dish:
            await callback.answer("Блюдо не найдено", show_alert=True)
            return

        # Деактивируем блюдо (мягкое удаление)
        await db.execute("UPDATE menu SET is_active = 0 WHERE id = ?", (dish_id,))
        await db.commit()

    await callback.answer(f"✅ Блюдо '{dish[0]}' удалено", show_alert=False)
    await admin_delete_dish(callback)

@dp.callback_query(F.data == "admin_add_courier")
async def admin_add_courier(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    text = (
        "➕ <b>Добавление курьера</b>\n\n"
        "Введите данные в формате:\n"
        "Имя | Телефон"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_couriers")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await state.set_state(OrderState.waiting_for_location)

@dp.message(OrderState.waiting_for_location)
async def process_add_courier(message: types.Message, state: FSMContext):
    parts = message.text.split("|")
    if len(parts) < 2:
        await message.answer("❌ Неверный формат. Используйте: Имя | Телефон")
        return

    name = parts[0].strip()
    phone = parts[1].strip()

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO couriers (name, phone, status) VALUES (?, ?, 'offline')",
            (name, phone)
        )
        await db.commit()

    await message.answer(f"✅ Курьер '{name}' добавлен!")
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В админ-панель", callback_data="admin_panel")
    builder.adjust(1)
    await message.answer("🏠 Главное меню", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "admin_create_promo")
async def admin_create_promo(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    text = (
        "➕ <b>Создание промокода</b>\n\n"
        "Введите данные в формате:\n"
        "КОД | Тип (percent/fixed/free_delivery) | Значение | Мин. заказ | Макс. использований\n\n"
        "Пример:\n"
        "<i>SALE20 | percent | 20 | 500 | 100</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_promo")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await state.set_state(OrderState.selecting_date_time)

@dp.message(OrderState.selecting_date_time)
async def process_create_promo(message: types.Message, state: FSMContext):
    parts = message.text.split("|")
    if len(parts) < 5:
        await message.answer("❌ Неверный формат. Проверьте пример и попробуйте снова")
        return

    code = parts[0].strip().upper()
    promo_type = parts[1].strip()
    try:
        value = int(parts[2].strip())
        min_order = int(parts[3].strip())
        max_uses = int(parts[4].strip())
    except ValueError:
        await message.answer("❌ Числовые поля должны быть числами")
        return

    if promo_type not in ['percent', 'fixed', 'free_delivery']:
        await message.answer("❌ Тип должен быть: percent, fixed или free_delivery")
        return

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            """INSERT INTO promo_codes (code, type, value, min_order, max_uses, created_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (code, promo_type, value, min_order, max_uses, message.from_user.id)
        )
        await db.commit()

    await message.answer(f"✅ Промокод '{code}' создан!")
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В админ-панель", callback_data="admin_panel")
    builder.adjust(1)
    await message.answer("🏠 Главное меню", reply_markup=builder.as_markup())

# ==================== ОБРАБОТЧИКИ СОСТОЯНИЙ ====================

@dp.message(OrderState.entering_address)
async def process_address(message: types.Message, state: FSMContext):
    """Обработка ввода адреса"""
    address = message.text.strip()

    # TODO: В будущем здесь будет проверка зоны доставки
    # Пока просто сохраняем адрес
    await state.update_data(address=address)

    # Спрашиваем время доставки
    text = (
        "🕐 <b>Время доставки</b>\n\n"
        "Выберите когда доставить:\n"
        "• Как можно скорее\n"
        "• К определенному времени\n\n"
        "Или введите время в формате ЧЧ:ММ"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="⚡ Как можно скорее", callback_data="delivery_asap")
    builder.button(text="📅 К определенному времени", callback_data="time_custom")
    builder.button(text="🔙 Назад", callback_data="cart")
    builder.adjust(1)

    await message.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await state.set_state(OrderState.selecting_date_time)

@dp.callback_query(F.data == "delivery_asap")
async def delivery_asap(callback: types.CallbackQuery, state: FSMContext):
    """Доставка как можно скорее"""
    delivery_time = (datetime.now() + timedelta(minutes=45)).isoformat()
    await state.update_data(delivery_time=delivery_time)

    # Переходим к сводке заказа
    await show_order_summary(callback, state)

# ==================== ЗАПУСК ====================

async def daily_tasks():
    """Ежедневные задачи"""
    logging.info("Выполнение ежедневных задач...")
    
    async with aiosqlite.connect(DB_NAME) as db:
        # Обновление уровней лояльности
        cursor = await db.execute(
            "SELECT user_id, total_spent FROM users"
        )
        users = await cursor.fetchall()
        
        for user_id, total_spent in users:
            new_level = LoyaltySystem.calculate_level(total_spent).value
            await db.execute(
                "UPDATE users SET loyalty_level = ? WHERE user_id = ?",
                (new_level, user_id)
            )
        
        # Очистка старых корзин (старше 3 дней)
        three_days_ago = (datetime.now() - timedelta(days=3)).isoformat()
        await db.execute(
            "DELETE FROM cart WHERE added_at < ?",
            (three_days_ago,)
        )
        
        # Архивация старых заказов (старше 1 года)
        # Реализация архивации...
        
        await db.commit()
    
    logging.info("Ежедневные задачи выполнены")

async def shutdown(signal_type=None):
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await bot.session.close()
    logging.info("Бот остановлен")
    
async def daily_broadcast():
    """Ежедневная рассылка блюда дня"""
    async with aiosqlite.connect(DB_NAME) as db:
        # Получаем подписчиков
        cursor = await db.execute(
            "SELECT user_id FROM subscribers WHERE is_active = 1 AND push_consent = 1"
        )
        subscribers = await cursor.fetchall()
        
        # Получаем блюдо дня
        today = datetime.now().strftime("%Y-%m-%d")
        cursor = await db.execute(
            """SELECT m.* FROM dish_of_day dod
               JOIN menu m ON dod.dish_id = m.id
               WHERE dod.date = ?""",
            (today,)
        )
        dish = await cursor.fetchone()
        
        if not dish:
            logging.info("Блюдо дня не установлено")
            return
        
        # Отправляем рассылку
        text = (
            f"🍽️ <b>Блюдо дня!</b>\n\n"
            f"<b>{dish[1]}</b>\n"
            f"{dish[2]}\n\n"
            f"💰 {dish[3]}₽\n"
            f"⭐ {dish[12]}/5\n\n"
            f"Закажите сейчас по специальной цене!"
        )
        
        for (user_id,) in subscribers:
            try:
                await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
            except Exception as e:
                logging.warning(f"Не удалось отправить сообщение {user_id}: {e}")

async def main():
    await init_db()
    
    # Настройка планировщика
    scheduler.add_job(daily_tasks, CronTrigger(hour=0, minute=0))
    scheduler.add_job(daily_broadcast, CronTrigger(hour=10, minute=0))  # Рассылка блюда дня
    scheduler.start()
    
    # Обработчики сигналов
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_event_loop().add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown(s.name)))
    
    try:
        await dp.start_polling(bot)
    finally:
        await shutdown()

if __name__ == "__main__":
    asyncio.run(main())