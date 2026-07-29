"""Инициализация базы данных и создание таблиц"""
import logging
from app.database import get_db

logger = logging.getLogger(__name__)


async def init_db():
    """Создание всех таблиц"""
    async with get_db() as db:
        # Пользователи
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
                allergens TEXT,
                registered_at TEXT,
                last_order_at TEXT,
                total_spent INTEGER DEFAULT 0,
                loyalty_points INTEGER DEFAULT 0,
                loyalty_level TEXT DEFAULT 'none',
                referral_code TEXT UNIQUE,
                referred_by INTEGER,
                is_verified INTEGER DEFAULT 0,
                favorite_dishes TEXT,
                order_history_stats TEXT
            )
        ''')

        # Меню
        await db.execute('''
            CREATE TABLE IF NOT EXISTS menu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                price INTEGER,
                cost_price INTEGER,
                image_url TEXT,
                is_active INTEGER DEFAULT 1,
                category TEXT,
                prep_time INTEGER,
                complexity INTEGER DEFAULT 1,
                allergens TEXT,
                diet_tags TEXT,
                ingredients TEXT,
                popularity_score INTEGER DEFAULT 0,
                rating REAL DEFAULT 5.0,
                total_reviews INTEGER DEFAULT 0
            )
        ''')

        # Заказы
        await db.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                items TEXT,
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
                current_stage TEXT,
                estimated_ready_time TEXT,
                actual_ready_time TEXT,
                courier_id INTEGER,
                payment_check_path TEXT,
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
                type TEXT,
                value INTEGER,
                min_order INTEGER DEFAULT 0,
                max_uses INTEGER,
                used_count INTEGER DEFAULT 0,
                valid_from TEXT,
                valid_until TEXT,
                applicable_users TEXT,
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
                sentiment_score REAL,
                categories TEXT,
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
                details TEXT
            )
        ''')

        # События
        await db.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                event_type TEXT,
                description TEXT,
                impact_factor REAL
            )
        ''')

        # Курьеры
        await db.execute('''
            CREATE TABLE IF NOT EXISTS couriers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                phone TEXT,
                status TEXT DEFAULT 'offline',
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
                polygon TEXT,
                is_active INTEGER DEFAULT 1
            )
        ''')

        # Подписчики
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

        # История баллов
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

        # === ИНДЕКСЫ ===
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_users_loyalty ON users(loyalty_level)",
            "CREATE INDEX IF NOT EXISTS idx_users_referral ON users(referral_code)",
            "CREATE INDEX IF NOT EXISTS idx_menu_active_category ON menu(is_active, category)",
            "CREATE INDEX IF NOT EXISTS idx_menu_popularity ON menu(popularity_score DESC)",
            "CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)",
            "CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_cart_user ON cart(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_kitchen_timers_order ON kitchen_timers(order_id)",
            "CREATE INDEX IF NOT EXISTS idx_kitchen_load_date_hour ON kitchen_load(date, hour)",
            "CREATE INDEX IF NOT EXISTS idx_analytics_date_type ON analytics(date, metric_type)",
            "CREATE INDEX IF NOT EXISTS idx_points_history_user ON points_history(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_reviews_order ON reviews(order_id)",
        ]

        for index_sql in indexes:
            await db.execute(index_sql)

        logger.info("✅ База данных инициализирована (таблицы + индексы)")

        # Инициализация зон доставки
        from app.services.delivery import init_default_zones
        await init_default_zones(db)
