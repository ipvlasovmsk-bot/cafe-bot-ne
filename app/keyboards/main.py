"""Клавиатуры для бота"""
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup
from app.utils.thai_time import format_price


def get_main_menu_keyboard(is_admin: bool = False, has_cart: bool = False) -> InlineKeyboardMarkup:
    """Главное меню"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🍽️ Меню", callback_data="menu")
    if has_cart:
        builder.button(text="🛒 Корзина", callback_data="cart")
    builder.button(text="🛠️ Конструктор", callback_data="constructor")
    builder.button(text="⭐ Избранное", callback_data="favorites")
    builder.button(text="🤖 Рекомендации", callback_data="recommendations")
    builder.button(text="🍲 Блюдо дня", callback_data="dish_of_day")
    builder.button(text="📦 Мои заказы", callback_data="my_orders")
    builder.button(text="📅 Бронирование", callback_data="reservation")
    builder.button(text="💎 Баллы", callback_data="loyalty")
    builder.button(text="👤 Профиль", callback_data="profile")
    builder.button(text="📍 Адрес кафе", callback_data="cafe_info")
    if is_admin:
        builder.button(text="🔧 Админ панель", callback_data="admin_panel")
    builder.adjust(2)
    return builder.as_markup()


def get_diet_filter_keyboard(selected: list[str] | None = None) -> InlineKeyboardMarkup:
    """Фильтр по диетам"""
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
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    builder.adjust(2)
    return builder.as_markup()


def get_back_keyboard(*callbacks: str) -> InlineKeyboardMarkup:
    """Универсальная кнопка 'Назад'"""
    builder = InlineKeyboardBuilder()
    for cb in callbacks:
        if cb == "main":
            builder.button(text="🔙 В главное меню", callback_data="back_to_main")
        else:
            builder.button(text="🔙 Назад", callback_data=cb)
    builder.adjust(1)
    return builder.as_markup()


def get_reservation_menu_keyboard() -> InlineKeyboardMarkup:
    """Меню бронирования столика"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Забронировать столик", callback_data="reserve_new")
    builder.button(text="📋 Мои бронирования", callback_data="reserve_my")
    builder.adjust(1)
    return builder.as_markup()


def get_location_filter_keyboard() -> InlineKeyboardMarkup:
    """Выбор локации для бронирования"""
    builder = InlineKeyboardBuilder()
    locations = [
        ("loc_any", "🏠 Все зоны"),
        ("loc_window", "🪟 У окна"),
        ("loc_hall", "🏛️ Центр зала"),
        ("loc_corner", "🛋️ Уютный уголок"),
        ("loc_vip", "👑 VIP-зона"),
        ("loc_terrace", "🌿 Терраса"),
    ]
    for cb, label in locations:
        builder.button(text=label, callback_data=cb)
    builder.button(text="❌ Отмена", callback_data="reserve_cancel")
    builder.adjust(2)
    return builder.as_markup()


def get_seats_keyboard(min_seats: int = 0) -> InlineKeyboardMarkup:
    """Выбор количества гостей"""
    builder = InlineKeyboardBuilder()
    options = [
        (1, "👤 1 гость"),
        (2, "👥 2 гостя"),
        (4, "👥 3-4 гостя"),
        (6, "👥 5-6 гостей"),
        (8, "👥 7-8 гостей"),
    ]
    for count, label in options:
        if count >= min_seats:
            builder.button(text=label, callback_data=f"seats_{count}")
    builder.button(text="🔙 Назад", callback_data="reserve_new")
    builder.adjust(2)
    return builder.as_markup()


def get_date_keyboard(date_options: list[str], current_month: str) -> InlineKeyboardMarkup:
    """Выбор даты — ближайшие 14 дней"""
    builder = InlineKeyboardBuilder()
    for date_str in date_options:
        builder.button(text=date_str, callback_data=f"date_{date_str}")
    builder.adjust(2)
    builder.button(text="🔙 Назад", callback_data="reserve_new")
    builder.button(text="❌ Отмена", callback_data="reserve_cancel")
    return builder.as_markup()


def get_time_keyboard(time_slots: list[str]) -> InlineKeyboardMarkup:
    """Выбор времени"""
    builder = InlineKeyboardBuilder()
    for slot in time_slots:
        builder.button(text=f"🕐 {slot}", callback_data=f"time_{slot}")
    if not time_slots:
        builder.button(text="❌ Нет свободных", callback_data="no_slots")
    builder.adjust(3)
    builder.button(text="🔙 Назад", callback_data="reserve_new")
    builder.button(text="❌ Отмена", callback_data="reserve_cancel")
    return builder.as_markup()


def get_table_keyboard(tables: list[dict]) -> InlineKeyboardMarkup:
    """Выбор столика"""
    builder = InlineKeyboardBuilder()
    for table in tables:
        seats = table["seats"]
        loc = table.get("location", "hall")
        loc_icon = {"window": "🪟", "hall": "🏛️", "corner": "🛋️", "vip": "👑", "terrace": "🌿"}.get(loc, "📍")
        builder.button(
            text=f"{loc_icon} {table['name']} ({seats} мест)",
            callback_data=f"table_{table['id']}"
        )
    builder.adjust(1)
    builder.button(text="🔙 Назад", callback_data="reserve_new")
    builder.button(text="❌ Отмена", callback_data="reserve_cancel")
    return builder.as_markup()


def get_reservation_confirm_keyboard(reservation_id: int) -> InlineKeyboardMarkup:
    """Подтверждение бронирования"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Забронировать", callback_data=f"reserve_confirm_{reservation_id}")
    builder.button(text="❌ Отмена", callback_data="reserve_cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_admin_reservation_keyboard(reservation_id: int) -> InlineKeyboardMarkup:
    """Админ-кнопки для бронирования"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"admin_reserve_confirm_{reservation_id}")
    builder.button(text="❌ Отклонить", callback_data=f"admin_reserve_reject_{reservation_id}")
    builder.button(text="💬 Добавить комментарий", callback_data=f"admin_reserve_comment_{reservation_id}")
    builder.button(text="🔙 Назад", callback_data="admin_reservations")
    builder.adjust(1)
    return builder.as_markup()


# ==================== КОНСТРУКТОР БЛЮД ====================

def get_dish_constructor_keyboard() -> InlineKeyboardMarkup:
    """Меню конструктора блюд"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🛠️ Создать блюдо", callback_data="constructor_start")
    builder.button(text="🔙 Назад", callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()


def get_template_keyboard(templates: list[dict]) -> InlineKeyboardMarkup:
    """Выбор шаблона блюда"""
    builder = InlineKeyboardBuilder()
    for t in templates:
        builder.button(
            text=f"{t['emoji']} {t['name']} (от {format_price(t['base_price'])})",
            callback_data=f"tmpl_{t['id']}"
        )
    builder.button(text="🔙 Отмена", callback_data="constructor_cancel")
    builder.adjust(1)
    return builder.as_markup()


def get_ingredients_keyboard(ingredients: list[dict], selected_ids: set[int] | None = None,
                              category_label: str = "Выберите",
                              max_select: int = 10, allow_multiple: bool = True) -> InlineKeyboardMarkup:
    """Выбор ингредиентов"""
    if selected_ids is None:
        selected_ids = set()

    builder = InlineKeyboardBuilder()
    for ing in ingredients:
        check = "✅ " if ing["id"] in selected_ids else ""
        builder.button(
            text=f"{check}{ing['name']} (+{format_price(ing['price'])})",
            callback_data=f"ing_{ing['id']}"
        )

    # Кнопки действий
    if selected_ids and allow_multiple:
        builder.button(text=f"✅ Выбрано: {len(selected_ids)} — Далее", callback_data="ing_done")
    elif not allow_multiple and selected_ids:
        builder.button(text="➡️ Далее", callback_data="ing_done")

    builder.button(text="⏭️ Пропустить", callback_data="ing_skip")
    builder.button(text="🔙 Назад", callback_data="constructor_back")
    builder.adjust(2)
    return builder.as_markup()


def get_single_ingredient_keyboard(ingredients: list[dict], selected_id: int | None = None,
                                     category_label: str = "Выберите") -> InlineKeyboardMarkup:
    """Выбор одного ингредиента (для одиночного выбора)"""
    builder = InlineKeyboardBuilder()
    for ing in ingredients:
        check = "✅ " if selected_id == ing["id"] else ""
        builder.button(
            text=f"{check}{ing['name']} (+{format_price(ing['price'])})",
            callback_data=f"ing_{ing['id']}"
        )
    if selected_id:
        builder.button(text="➡️ Далее", callback_data="ing_done")
    builder.button(text="⏭️ Пропустить", callback_data="ing_skip")
    builder.button(text="🔙 Назад", callback_data="constructor_back")
    builder.adjust(2)
    return builder.as_markup()


def get_constructor_review_keyboard() -> InlineKeyboardMarkup:
    """Финальное меню конструктора"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🛒 Добавить в корзину", callback_data="constructor_to_cart")
    builder.button(text="✏️ Изменить состав", callback_data="constructor_edit")
    builder.button(text="❌ Отмена", callback_data="constructor_cancel")
    builder.adjust(1)
    return builder.as_markup()
