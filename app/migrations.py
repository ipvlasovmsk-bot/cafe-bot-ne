"""Система миграций базы данных"""
import os
import logging
import aiosqlite
from app.config import DB_NAME
from app.database import get_db

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")


class Migration:
    """Одна миграция"""

    def __init__(self, version: int, name: str, up_sql: str, down_sql: str = ""):
        self.version = version
        self.name = name
        self.up_sql = up_sql
        self.down_sql = down_sql

    async def apply(self, db: aiosqlite.Connection):
        """Применить миграцию"""
        for sql in self.up_sql.split(";"):
            sql = sql.strip()
            if sql:
                await db.execute(sql)
        logger.info(f"[MIGRATION] Применена v{self.version}: {self.name}")

    async def rollback(self, db: aiosqlite.Connection):
        """Откатить миграцию"""
        if self.down_sql:
            for sql in self.down_sql.split(";"):
                sql = sql.strip()
                if sql:
                    await db.execute(sql)
            logger.info(f"[MIGRATION] Откачена v{self.version}: {self.name}")


async def _ensure_migrations_table(db: aiosqlite.Connection):
    """Таблица для отслеживания миграций"""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)


async def _get_applied_versions(db: aiosqlite.Connection) -> list[int]:
    """Получить список применённых миграций"""
    cursor = await db.execute("SELECT version FROM schema_migrations ORDER BY version")
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


# ==================== МИГРАЦИИ ====================

MIGRATIONS = [
    Migration(
        version=1,
        name="initial_schema",
        up_sql="""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT, first_name TEXT, last_name TEXT,
                phone TEXT, email TEXT, birth_date TEXT,
                diet_type TEXT DEFAULT 'none', allergens TEXT,
                registered_at TEXT, last_order_at TEXT,
                total_spent INTEGER DEFAULT 0,
                loyalty_points INTEGER DEFAULT 0,
                loyalty_level TEXT DEFAULT 'none',
                referral_code TEXT UNIQUE, referred_by INTEGER,
                is_verified INTEGER DEFAULT 0,
                favorite_dishes TEXT, order_history_stats TEXT
            );
            CREATE TABLE IF NOT EXISTS menu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, description TEXT, price INTEGER, cost_price INTEGER,
                image_url TEXT, is_active INTEGER DEFAULT 1, category TEXT,
                prep_time INTEGER, complexity INTEGER DEFAULT 1,
                allergens TEXT, diet_tags TEXT, ingredients TEXT,
                popularity_score INTEGER DEFAULT 0, rating REAL DEFAULT 5.0,
                total_reviews INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, items TEXT,
                address TEXT, lat REAL, lon REAL, delivery_zone TEXT,
                delivery_time TEXT, priority TEXT DEFAULT 'normal',
                total_price INTEGER, discount_applied INTEGER DEFAULT 0,
                points_earned INTEGER, points_spent INTEGER DEFAULT 0,
                promo_code TEXT, status TEXT DEFAULT 'new', current_stage TEXT,
                estimated_ready_time TEXT, actual_ready_time TEXT,
                courier_id INTEGER, created_at TEXT, updated_at TEXT,
                review_requested INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS kitchen_timers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER,
                stage TEXT, start_time TEXT, estimated_end TEXT,
                actual_end TEXT, is_completed INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS kitchen_load (
                id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, hour INTEGER,
                max_capacity INTEGER, current_load INTEGER DEFAULT 0,
                is_blocked INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS cart (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                dish_id INTEGER, dish_name TEXT, ingredients TEXT,
                extra_price INTEGER, base_price INTEGER, added_at TEXT
            );
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY, type TEXT, value INTEGER,
                min_order INTEGER DEFAULT 0, max_uses INTEGER,
                used_count INTEGER DEFAULT 0, valid_from TEXT, valid_until TEXT,
                applicable_users TEXT, created_by INTEGER
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER,
                user_id INTEGER, rating INTEGER, text TEXT,
                sentiment_score REAL, categories TEXT, created_at TEXT,
                is_published INTEGER DEFAULT 1, admin_reply TEXT
            );
            CREATE TABLE IF NOT EXISTS analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, hour INTEGER,
                metric_type TEXT, metric_value REAL, details TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT,
                event_type TEXT, description TEXT, impact_factor REAL
            );
            CREATE TABLE IF NOT EXISTS couriers (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT,
                status TEXT DEFAULT 'offline', current_lat REAL,
                current_lon REAL, last_update TEXT
            );
            CREATE TABLE IF NOT EXISTS delivery_zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,
                min_order INTEGER, delivery_cost INTEGER, free_from INTEGER,
                polygon TEXT, is_active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS subscribers (
                user_id INTEGER PRIMARY KEY, is_active INTEGER DEFAULT 1,
                email_consent INTEGER DEFAULT 0, sms_consent INTEGER DEFAULT 0,
                push_consent INTEGER DEFAULT 1, unsubscribed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS dish_of_day (
                id INTEGER PRIMARY KEY AUTOINCREMENT, dish_id INTEGER,
                special_price INTEGER, date TEXT, orders_count INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS ab_tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, test_name TEXT,
                variant_a TEXT, variant_b TEXT, user_segment TEXT,
                start_date TEXT, end_date TEXT, is_active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS points_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                amount INTEGER, type TEXT, order_id INTEGER, created_at TEXT
            );
        """,
        down_sql=""  # Не откатываем начальную схему
    ),
    Migration(
        version=2,
        name="add_indexes",
        up_sql="""
            CREATE INDEX IF NOT EXISTS idx_users_loyalty ON users(loyalty_level);
            CREATE INDEX IF NOT EXISTS idx_users_referral ON users(referral_code);
            CREATE INDEX IF NOT EXISTS idx_menu_active_category ON menu(is_active, category);
            CREATE INDEX IF NOT EXISTS idx_menu_popularity ON menu(popularity_score DESC);
            CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
            CREATE INDEX IF NOT EXISTS idx_cart_user ON cart(user_id);
            CREATE INDEX IF NOT EXISTS idx_kitchen_timers_order ON kitchen_timers(order_id);
            CREATE INDEX IF NOT EXISTS idx_kitchen_load_date_hour ON kitchen_load(date, hour);
            CREATE INDEX IF NOT EXISTS idx_analytics_date_type ON analytics(date, metric_type);
            CREATE INDEX IF NOT EXISTS idx_points_history_user ON points_history(user_id);
            CREATE INDEX IF NOT EXISTS idx_reviews_order ON reviews(order_id);
        """,
        down_sql="DROP INDEX IF EXISTS idx_users_loyalty; DROP INDEX IF EXISTS idx_users_referral;"
    ),
    Migration(
        version=3,
        name="add_default_delivery_zone",
        up_sql="""
            INSERT OR IGNORE INTO delivery_zones (name, min_order, delivery_cost, free_from, polygon, is_active)
            VALUES ('Центральная', 500, 199, 1500, '[[55.8008, 37.5723], [55.8008, 37.6623], [55.7108, 37.6623], [55.7108, 37.5723]]', 1);
        """,
        down_sql="DELETE FROM delivery_zones WHERE name = 'Центральная';"
    ),
    Migration(
        version=4,
        name="table_reservations",
        up_sql="""
            CREATE TABLE IF NOT EXISTS cafe_tables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                seats INTEGER NOT NULL,
                location TEXT DEFAULT 'hall',
                is_active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS table_reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                table_id INTEGER NOT NULL,
                reservation_date TEXT NOT NULL,
                reservation_time TEXT NOT NULL,
                guest_count INTEGER NOT NULL,
                guest_name TEXT,
                guest_phone TEXT,
                special_requests TEXT,
                status TEXT DEFAULT 'pending',
                admin_comment TEXT,
                created_at TEXT,
                updated_at TEXT,
                FOREIGN KEY (table_id) REFERENCES cafe_tables(id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_reservations_user ON table_reservations(user_id);
            CREATE INDEX IF NOT EXISTS idx_reservations_date ON table_reservations(reservation_date);
            CREATE INDEX IF NOT EXISTS idx_reservations_status ON table_reservations(status);
            CREATE INDEX IF NOT EXISTS idx_reservations_table_date ON table_reservations(table_id, reservation_date, reservation_time);
        """,
        down_sql="DROP INDEX IF EXISTS idx_reservations_table_date; DROP INDEX IF EXISTS idx_reservations_status; DROP INDEX IF EXISTS idx_reservations_date; DROP INDEX IF EXISTS idx_reservations_user; DROP TABLE IF EXISTS table_reservations; DROP TABLE IF EXISTS cafe_tables;"
    ),
    Migration(
        version=5,
        name="seed_default_tables",
        up_sql="""
            INSERT OR IGNORE INTO cafe_tables (name, seats, location, is_active) VALUES
                ('Столик у окна #1', 2, 'window', 1),
                ('Столик у окна #2', 2, 'window', 1),
                ('Столик у окна #3', 4, 'window', 1),
                ('Центральный #4', 4, 'hall', 1),
                ('Центральный #5', 4, 'hall', 1),
                ('Центральный #6', 6, 'hall', 1),
                ('Уютный #7', 2, 'corner', 1),
                ('Уютный #8', 6, 'corner', 1),
                ('VIP #9', 8, 'vip', 1),
                ('Терраса #10', 4, 'terrace', 1),
                ('Терраса #11', 6, 'terrace', 1),
                ('Терраса #12', 8, 'terrace', 1);
        """,
        down_sql="DELETE FROM cafe_tables;"
    ),
    # === Добавляйте новые миграции сюда ===
    Migration(
        version=6,
        name="dish_constructor",
        up_sql="""
            -- Категории ингредиентов (основа, добавка, соус, гарнир)
            CREATE TABLE IF NOT EXISTS ingredient_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category_type TEXT NOT NULL,  -- base, topping, sauce, side
                sort_order INTEGER DEFAULT 0
            );
            -- Ингредиенты
            CREATE TABLE IF NOT EXISTS ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price INTEGER DEFAULT 0,
                category_id INTEGER,
                is_active INTEGER DEFAULT 1,
                allergens TEXT,
                diet_tags TEXT,
                calories INTEGER,
                sort_order INTEGER DEFAULT 0,
                FOREIGN KEY (category_id) REFERENCES ingredient_categories(id)
            );
            -- Шаблоны конструктора блюд (салат, паста, вок...)
            CREATE TABLE IF NOT EXISTS dish_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                base_price INTEGER DEFAULT 0,
                emoji TEXT,
                is_active INTEGER DEFAULT 1,
                max_toppings INTEGER DEFAULT 5,
                max_sauces INTEGER DEFAULT 2
            );
            -- Связь шаблонов с категориями (какие категории доступны в каком шаблоне)
            CREATE TABLE IF NOT EXISTS dish_template_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                template_id INTEGER,
                category_id INTEGER,
                is_required INTEGER DEFAULT 0,
                min_select INTEGER DEFAULT 1,
                max_select INTEGER DEFAULT 10,
                label TEXT,
                FOREIGN KEY (template_id) REFERENCES dish_templates(id),
                FOREIGN KEY (category_id) REFERENCES ingredient_categories(id)
            );
            CREATE INDEX IF NOT EXISTS idx_ingredients_category ON ingredients(category_id);
            CREATE INDEX IF NOT EXISTS idx_ingredients_active ON ingredients(is_active);
            CREATE INDEX IF NOT EXISTS idx_dish_templates_active ON dish_templates(is_active);
        """,
        down_sql="DROP INDEX IF EXISTS idx_dish_templates_active; DROP INDEX IF EXISTS idx_ingredients_active; DROP INDEX IF EXISTS idx_ingredients_category; DROP TABLE IF EXISTS dish_template_categories; DROP TABLE IF EXISTS dish_templates; DROP TABLE IF EXISTS ingredients; DROP TABLE IF EXISTS ingredient_categories;"
    ),
    Migration(
        version=7,
        name="seed_ingredients_and_templates",
        up_sql="""
            -- Категории ингредиентов
            INSERT INTO ingredient_categories (name, category_type, sort_order) VALUES
                ('Мясо и белок', 'base', 1),
                ('Гарнир', 'side', 2),
                ('Овощи и зелень', 'topping', 3),
                ('Сыры и добавки', 'topping', 4),
                ('Соусы', 'sauce', 5);

            -- Ингредиенты — Мясо и белок
            INSERT INTO ingredients (name, price, category_id, allergens, calories, sort_order) VALUES
                ('Куриное филе', 120, 1, '', 165, 1),
                ('Говядина', 180, 1, '', 250, 2),
                ('Свинина', 150, 1, '', 240, 3),
                ('Лосось', 220, 1, 'fish', 210, 4),
                ('Креветки', 200, 1, 'shellfish', 99, 5),
                ('Тофу', 90, 1, 'soy', 76, 6),
                ('Яйцо', 40, 1, 'egg', 155, 7),
                ('Бекон', 100, 1, '', 420, 8);

            -- Ингредиенты — Гарнир
            INSERT INTO ingredients (name, price, category_id, allergens, calories, sort_order) VALUES
                ('Рис', 50, 2, '', 130, 1),
                ('Паста', 60, 2, 'gluten', 131, 2),
                ('Гречка', 55, 2, '', 132, 3),
                ('Картофель', 40, 2, '', 77, 4),
                ('Лапша удон', 70, 2, 'gluten', 130, 5),
                ('Киноа', 80, 2, '', 120, 6),
                ('Спагетти', 60, 2, 'gluten', 131, 7);

            -- Ингредиенты — Овощи и зелень
            INSERT INTO ingredients (name, price, category_id, diet_tags, calories, sort_order) VALUES
                ('Помидоры', 30, 3, 'vegan,vegetarian', 18, 1),
                ('Огурцы', 25, 3, 'vegan,vegetarian', 15, 2),
                ('Перец болгарский', 35, 3, 'vegan,vegetarian', 27, 3),
                ('Салат айсберг', 20, 3, 'vegan,vegetarian', 14, 4),
                ('Руккола', 35, 3, 'vegan,vegetarian', 25, 5),
                ('Кукуруза', 30, 3, 'vegan,vegetarian', 86, 6),
                ('Авокадо', 60, 3, 'vegan,vegetarian', 160, 7),
                ('Грибы шампиньоны', 40, 3, 'vegan,vegetarian', 22, 8),
                ('Лук красный', 20, 3, 'vegan,vegetarian', 40, 9),
                ('Маслины', 35, 3, 'vegan,vegetarian', 115, 10),
                ('Капуста брокколи', 30, 3, 'vegan,vegetarian', 34, 11),
                ('Морковь', 20, 3, 'vegan,vegetarian', 41, 12);

            -- Ингредиенты — Сыры и добавки
            INSERT INTO ingredients (name, price, category_id, allergens, diet_tags, calories, sort_order) VALUES
                ('Пармезан', 70, 4, 'dairy', 'vegetarian', 431, 1),
                ('Моцарелла', 60, 4, 'dairy', 'vegetarian', 280, 2),
                ('Чеддер', 65, 4, 'dairy', 'vegetarian', 403, 3),
                ('Фета', 55, 4, 'dairy', 'vegetarian', 264, 4),
                ('Кешью', 50, 4, 'nuts', 'vegan,vegetarian', 553, 5),
                ('Кунжут', 30, 4, '', 'vegan,vegetarian', 573, 6),
                ('Яйцо пашот', 50, 4, 'egg', 'vegetarian', 155, 7),
                ('Халапеньо', 25, 4, '', 'vegan,vegetarian', 29, 8);

            -- Ингредиенты — Соусы
            INSERT INTO ingredients (name, price, category_id, allergens, diet_tags, calories, sort_order) VALUES
                ('Томатный соус', 20, 5, '', 'vegan', 30, 1),
                ('Сливочный соус', 25, 5, 'dairy', 'vegetarian', 150, 2),
                ('Соевый соус', 15, 5, 'soy', 'vegan', 53, 3),
                ('Песто', 35, 5, 'nuts,dairy', 'vegetarian', 320, 4),
                ('Барбекю', 25, 5, '', '', 170, 5),
                ('Чесночный', 20, 5, 'dairy', 'vegetarian', 120, 6),
                ('Терияки', 25, 5, 'soy', '', 90, 7),
                ('Оливковое масло', 15, 5, '', 'vegan', 884, 8),
                ('Сметана', 15, 5, 'dairy', 'vegetarian', 200, 9),
                ('Шрирача', 20, 5, '', 'vegan', 40, 10);

            -- Шаблоны конструктора блюд
            INSERT INTO dish_templates (name, description, base_price, emoji, is_active, max_toppings, max_sauces) VALUES
                ('Салат', 'Свежий салат с выбором основы и топпингов', 150, '🥗', 1, 6, 2),
                ('Паста', 'Итальянская паста на ваш вкус', 200, '🍝', 1, 5, 2),
                ('Боул', 'Сытный боул с рисом или киноа', 220, '🥣', 1, 6, 2),
                ('Вок', 'Азиатский вок с лапшой', 210, '🍜', 1, 5, 2),
                ('Бургер', 'Собери свой бургер', 180, '🍔', 1, 5, 2),
                ('Завтрак', 'Завтрак на весь день', 160, '🍳', 1, 4, 2);

            -- Связи шаблонов с категориями
            -- Салат (id=1): белок -> овощи/сыры -> соусы
            INSERT INTO dish_template_categories (template_id, category_id, is_required, min_select, max_select, label) VALUES
                (1, 1, 0, 0, 1, 'Выберите белок (необязательно)'),
                (1, 3, 1, 1, 6, 'Выберите овощи и зелень'),
                (1, 4, 0, 0, 3, 'Добавьте сыр или орехи'),
                (1, 5, 0, 0, 2, 'Выберите заправку');

            -- Паста (id=2): гарнир -> белок -> топпинги -> соусы
            INSERT INTO dish_template_categories (template_id, category_id, is_required, min_select, max_select, label) VALUES
                (2, 2, 1, 1, 1, 'Выберите вид пасты'),
                (2, 1, 0, 0, 1, 'Добавьте мясо или белок'),
                (2, 3, 0, 0, 3, 'Овощи и добавки'),
                (2, 5, 0, 0, 2, 'Выберите соус');

            -- Боул (id=3): гарнир -> белок -> овощи/сыры -> соусы
            INSERT INTO dish_template_categories (template_id, category_id, is_required, min_select, max_select, label) VALUES
                (3, 2, 1, 1, 1, 'Выберите основу (рис, киноа)'),
                (3, 1, 0, 0, 1, 'Добавьте белок'),
                (3, 3, 0, 0, 4, 'Овощи и зелень'),
                (3, 4, 0, 0, 2, 'Сыр или добавки'),
                (3, 5, 0, 0, 2, 'Соус');

            -- Вок (id=4): гарнир -> белок -> овощи -> соусы
            INSERT INTO dish_template_categories (template_id, category_id, is_required, min_select, max_select, label) VALUES
                (4, 2, 1, 1, 1, 'Выберите лапшу'),
                (4, 1, 0, 0, 1, 'Добавьте мясо или креветки'),
                (4, 3, 0, 0, 3, 'Овощи'),
                (4, 5, 0, 0, 2, 'Соус');

            -- Бургер (id=5): белкот -> гарнир -> топпинги -> соусы
            INSERT INTO dish_template_categories (template_id, category_id, is_required, min_select, max_select, label) VALUES
                (5, 1, 1, 1, 1, 'Выберите котлету'),
                (5, 3, 0, 0, 3, 'Овощи и добавки'),
                (5, 4, 0, 0, 2, 'Сыр и дополнения'),
                (5, 5, 0, 0, 2, 'Соус');

            -- Завтрак (id=6): белок -> гарнир -> топпинги -> соусы
            INSERT INTO dish_template_categories (template_id, category_id, is_required, min_select, max_select, label) VALUES
                (6, 1, 1, 1, 1, 'Выберите основу завтрака'),
                (6, 2, 0, 0, 1, 'Гарнир'),
                (6, 3, 0, 0, 2, 'Добавки'),
                (6, 5, 0, 0, 2, 'Соус');
        """,
        down_sql="DELETE FROM dish_template_categories; DELETE FROM dish_templates; DELETE FROM ingredients; DELETE FROM ingredient_categories;"
    ),
    Migration(
        version=8,
        name="add_payment_check_to_orders",
        up_sql="""
            ALTER TABLE orders ADD COLUMN payment_check_path TEXT;
        """,
        down_sql="ALTER TABLE orders DROP COLUMN payment_check_path;"
    ),
    Migration(
        version=9,
        name="add_courier_photo_to_orders",
        up_sql="""
            ALTER TABLE orders ADD COLUMN courier_photo_file_id TEXT;
        """,
        down_sql="ALTER TABLE orders DROP COLUMN courier_photo_file_id;"
    ),
]


async def run_migrations():
    """Применить все ожидающие миграции"""
    async with get_db() as db:
        await _ensure_migrations_table(db)
        applied = await _get_applied_versions(db)

        for migration in MIGRATIONS:
            if migration.version in applied:
                continue

            try:
                await migration.apply(db)
                await db.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                    (migration.version, migration.name)
                )
            except Exception as e:
                logger.error(f"[MIGRATION] Ошибка v{migration.version}: {e}")
                await db.rollback()
                raise

        logger.info(f"[MIGRATION] Применено. Последняя версия: {MIGRATIONS[-1].version}")


async def rollback_migration(target_version: int | None = None):
    """Откатить миграцию до указанной версии"""
    async with get_db() as db:
        await _ensure_migrations_table(db)
        applied = await _get_applied_versions(db)

        for migration in reversed(MIGRATIONS):
            if migration.version not in applied:
                continue
            if target_version is not None and migration.version <= target_version:
                break

            await migration.rollback(db)
            await db.execute(
                "DELETE FROM schema_migrations WHERE version = ?",
                (migration.version,)
            )

        logger.info("[MIGRATION] Откат завершён")
