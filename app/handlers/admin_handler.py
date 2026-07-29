"""Админ-панель"""
import asyncio
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import ADMIN_IDS, TIMEZONE_OFFSET, CURRENCY_SYMBOL
from app.database import get_db
from app.states import AdminStates
from app.services.analytics import AnalyticsManager
from app.services.kitchen import KitchenLoadManager
from app.keyboards.main import get_back_keyboard
from app.utils.thai_time import format_price, format_thailand_time, format_thailand_date

logger = logging.getLogger(__name__)
admin_router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@admin_router.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    # Проверяем количество ожидающих чеков
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM orders WHERE status = 'payment_pending'"
        )
        pending_checks = (await cursor.fetchone())[0]

    text = "🔧 <b>Админ-панель</b>\n\nВыберите раздел для управления:"

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Заказы", callback_data="admin_orders")
    if pending_checks > 0:
        builder.button(text=f"💳 Чеки ({pending_checks})", callback_data="admin_payment_checks")
    else:
        builder.button(text="💳 Чеки", callback_data="admin_payment_checks")
    builder.button(text="🍽️ Меню", callback_data="admin_menu")
    builder.button(text="🚚 Курьеры", callback_data="admin_couriers")
    builder.button(text="📅 Бронирования", callback_data="admin_reservations")
    builder.button(text="🎁 Промокоды", callback_data="admin_promo")
    builder.button(text="📊 Аналитика", callback_data="admin_analytics")
    builder.button(text="🏢 Загрузка кухни", callback_data="admin_kitchen_load")
    builder.button(text="📢 Рассылка", callback_data="admin_broadcast")
    builder.button(text="🔙 В главное меню", callback_data="back_to_main")
    builder.adjust(2)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data == "admin_orders")
async def admin_orders_redirect(callback: CallbackQuery):
    """Редирект на новый обработчик заказов"""
    # Передаём управление в admin_order_router
    from app.handlers.admin_order_handler import admin_orders_list
    await admin_orders_list(callback, callback.message.bot)


@admin_router.callback_query(F.data == "admin_menu")
async def admin_menu(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    text = "🍽️ <b>Управление меню</b>\n\nВыберите действие:"

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить блюдо", callback_data="admin_add_dish")
    builder.button(text="📝 Редактировать", callback_data="admin_edit_dish")
    builder.button(text="❌ Удалить блюдо", callback_data="admin_delete_dish")
    builder.button(text="🔙 Назад", callback_data="admin_panel")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data == "admin_add_dish")
async def admin_add_dish(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    text = (
        "➕ <b>Добавление блюда</b>\n\n"
        "Шаг 1: Отправьте <b>фото блюда</b>.\n\n"
        "Шаг 2: Затем отправьте данные в формате:\n"
        "<i>Название | Описание | Цена | Категория | Время приготовления(мин)</i>\n\n"
        "Пример:\n"
        "<i>Бургер Классик | Сочная котлета, свежие овощи | 350 | burger | 20</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_menu")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await state.set_state(AdminStates.adding_dish_photo)


@admin_router.message(AdminStates.adding_dish_photo)
async def receive_dish_photo(message: Message, state: FSMContext):
    """Получение фото блюда"""
    if not _is_admin(message.from_user.id):
        return

    if not message.photo:
        await message.answer("❌ Пожалуйста, отправьте фото блюда.")
        return

    # Получаем лучшее качество фото (последнее в списке)
    photo = message.photo[-1]
    file_id = photo.file_id

    # Сохраняем file_id во временное хранилище
    await state.update_data(dish_image_file_id=file_id)

    await message.answer(
        "✅ Фото получено!\n\n"
        "Теперь отправьте данные блюда:\n"
        "<i>Название | Описание | Цена | Категория | Время приготовления(мин)</i>",
        parse_mode=ParseMode.HTML
    )
    await state.set_state(AdminStates.adding_dish)


@admin_router.message(AdminStates.adding_dish)
async def process_add_dish(message: Message, state: FSMContext):
    parts = message.text.split("|")
    if len(parts) < 5:
        await message.answer("❌ Неверный формат. Используйте: Название | Описание | Цена | Категория | Время")
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

    # Получаем file_id фото из состояния
    data = await state.get_data()
    image_file_id = data.get("dish_image_file_id")

    async with get_db() as db:
        # Вставляем блюдо с фото (file_id будет сохранён как image_url для простоты)
        await db.execute(
            "INSERT INTO menu (name, description, price, category, prep_time, is_active, image_url) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (name, description, price, category, prep_time, image_file_id)
        )

    await message.answer(f"✅ Блюдо '{name}' добавлено в меню с фото!")
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В админ-панель", callback_data="admin_panel")
    await message.answer("🏠 Главное меню", reply_markup=builder.as_markup())


@admin_router.callback_query(F.data == "admin_edit_dish")
async def admin_edit_dish(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    async with get_db() as db:
        cursor = await db.execute("SELECT id, name, price, is_active FROM menu ORDER BY id DESC LIMIT 20")
        dishes = await cursor.fetchall()

    text = "📝 <b>Редактирование меню</b>\n\n"
    for dish in dishes:
        status = "✅" if dish[3] else "❌"
        text += f"{status} #{dish[0]} {dish[1]} - {format_price(dish[2])}\n"

    text += "\nВведите /edit_dish ID | Новое_название | Новая_цена"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_menu")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data == "admin_delete_dish")
async def admin_delete_dish(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, price FROM menu WHERE is_active = 1 ORDER BY id DESC LIMIT 20"
        )
        dishes = await cursor.fetchall()

    text = "❌ <b>Удаление блюда</b>\n\n"
    builder = InlineKeyboardBuilder()

    for dish in dishes:
        text += f"#{dish[0]} {dish[1]} - {format_price(dish[2])}\n"
        builder.button(text=f"🗑️ {dish[1][:20]}", callback_data=f"admin_dish_delete_{dish[0]}")

    builder.button(text="🔙 Назад", callback_data="admin_menu")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data.startswith("admin_dish_delete_"))
async def confirm_delete_dish(callback: CallbackQuery):
    try:
        dish_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return

    async with get_db() as db:
        cursor = await db.execute("SELECT name FROM menu WHERE id = ?", (dish_id,))
        dish = await cursor.fetchone()

        if not dish:
            await callback.answer("Блюдо не найдено", show_alert=True)
            return

        await db.execute("UPDATE menu SET is_active = 0 WHERE id = ?", (dish_id,))

    await callback.answer(f"✅ Блюдо '{dish[0]}' удалено", show_alert=False)
    await admin_delete_dish(callback)


@admin_router.callback_query(F.data == "admin_couriers")
async def admin_couriers(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    async with get_db() as db:
        cursor = await db.execute("SELECT id, name, phone, status FROM couriers")
        couriers = await cursor.fetchall()

    text = "🚚 <b>Курьеры</b>\n\n"
    status_icons = {'offline': '⚫', 'online': '🟢', 'busy': '🔴'}

    for c in couriers:
        icon = status_icons.get(c[3], '❓')
        text += f"{icon} {c[1]} — {c[2]} ({c[3]})\n"

    if not couriers:
        text += "Курьеров пока нет."

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Добавить курьера", callback_data="admin_add_courier")
    builder.button(text="🔙 Назад", callback_data="admin_panel")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data == "admin_add_courier")
async def admin_add_courier(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    text = "➕ <b>Добавление курьера</b>\n\nВведите данные в формате:\n<i>Имя | Телефон</i>"

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_couriers")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await state.set_state(AdminStates.adding_courier)


@admin_router.message(AdminStates.adding_courier)
async def process_add_courier(message: Message, state: FSMContext):
    parts = message.text.split("|")
    if len(parts) < 2:
        await message.answer("❌ Неверный формат. Используйте: Имя | Телефон")
        return

    name = parts[0].strip()
    phone = parts[1].strip()

    async with get_db() as db:
        await db.execute(
            "INSERT INTO couriers (name, phone, status) VALUES (?, ?, 'offline')",
            (name, phone)
        )

    await message.answer(f"✅ Курьер '{name}' добавлен!")
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В админ-панель", callback_data="admin_panel")
    await message.answer("🏠 Главное меню", reply_markup=builder.as_markup())


@admin_router.callback_query(F.data == "admin_promo")
async def admin_promo(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    async with get_db() as db:
        cursor = await db.execute("SELECT code, type, value, max_uses, used_count FROM promo_codes")
        promos = await cursor.fetchall()

    text = "🎁 <b>Промокоды</b>\n\n"
    for p in promos:
        remaining = p[3] - p[4] if p[3] else '∞'
        text += f"{p[0]}: {p[2]} ({remaining} осталось)\n"

    if not promos:
        text += "Промокодов пока нет."

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать промокод", callback_data="admin_create_promo")
    builder.button(text="🔙 Назад", callback_data="admin_panel")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data == "admin_create_promo")
async def admin_create_promo(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    text = (
        "➕ <b>Создание промокода</b>\n\n"
        "Введите данные в формате:\n"
        "<i>КОД | Тип (percent/fixed/free_delivery) | Значение | Мин. заказ | Макс. использований</i>\n\n"
        "Пример:\n"
        "<i>SALE20 | percent | 20 | 500 | 100</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_promo")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await state.set_state(AdminStates.creating_promo)


@admin_router.message(AdminStates.creating_promo)
async def process_create_promo(message: Message, state: FSMContext):
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

    async with get_db() as db:
        await db.execute(
            "INSERT INTO promo_codes (code, type, value, min_order, max_uses, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (code, promo_type, value, min_order, max_uses, message.from_user.id)
        )

    await message.answer(f"✅ Промокод '{code}' создан!")
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 В админ-панель", callback_data="admin_panel")
    await message.answer("🏠 Главное меню", reply_markup=builder.as_markup())


@admin_router.callback_query(F.data == "admin_analytics")
async def admin_analytics(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    async with get_db() as db:
        analytics_mgr = AnalyticsManager(db)
        dashboard = await analytics_mgr.get_dashboard_data()

    text = (
        f"📊 <b>Аналитика</b>\n\n"
        f"📦 Заказов сегодня: {dashboard['today_orders']}\n"
        f"💰 Выручка сегодня: {format_price(dashboard['today_revenue'])}\n"
        f"👨‍🍳 В работе: {dashboard['in_progress']}\n"
        f"⏱️ Среднее время приготовления: {dashboard['avg_prep_time']} мин\n"
        f"🏢 Загрузка кухни: {dashboard['kitchen_load']['current']}/{dashboard['kitchen_load']['max']} "
        f"({dashboard['kitchen_load']['percent']}%)\n\n"
        f"🏆 Топ блюд сегодня:\n"
    )

    for i, (dish_name, count) in enumerate(dashboard['top_dishes'], 1):
        text += f"{i}. {dish_name} - {count} шт.\n"

    if not dashboard['top_dishes']:
        text += "Пока нет данных."

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_panel")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@admin_router.callback_query(F.data == "admin_kitchen_load")
async def admin_kitchen_load(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    today = datetime.now().date()
    async with get_db() as db:
        klm = KitchenLoadManager(db)
        available_slots = await klm.get_available_slots(today)

    text = f"🏢 <b>Загрузка кухни на {format_thailand_date(today, '%d.%m.%Y')}</b>\n\n"

    for hour in range(10, 23):
        status = "✅" if hour in available_slots else "❌"
        text += f"{status} {hour:02d}:00\n"

    text += "\nНажмите на час, чтобы заблокировать слот."

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


@admin_router.callback_query(F.data.startswith("toggle_slot_"))
async def toggle_slot(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    parts = callback.data.split("_")
    if len(parts) >= 4:
        date_str = parts[2]
        try:
            hour = int(parts[3])
        except (ValueError, IndexError):
            await callback.answer("[ERR] Ошибка данных", show_alert=True)
            return

        async with get_db() as db:
            klm = KitchenLoadManager(db)
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d").date()
                await klm.block_slot(date, hour)
                await callback.answer("Слот заблокирован", show_alert=False)
                await admin_kitchen_load(callback)
            except ValueError:
                await callback.answer("Неверный формат даты", show_alert=True)


@admin_router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    text = (
        "📢 <b>Рассылка сообщений</b>\n\n"
        "Напишите сообщение для рассылки всем подписчикам."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_panel")

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await state.set_state(AdminStates.broadcasting)


@admin_router.message(AdminStates.broadcasting)
async def process_broadcast(message: Message, state: FSMContext):
    """Рассылка"""
    if not _is_admin(message.from_user.id):
        return

    broadcast_text = message.text

    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT user_id FROM subscribers WHERE is_active = 1"
            )
            subscribers = await cursor.fetchall()

        success_count = 0
        fail_count = 0

        for (user_id,) in subscribers:
            try:
                # Bot будет передан через data
                await message.bot.send_message(user_id, broadcast_text)
                success_count += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                fail_count += 1
                logger.warning(f"Не удалось отправить сообщение {user_id}: {e}")

        await message.answer(
            f"✅ Рассылка завершена!\n\nУспешно: {success_count}\nОшибок: {fail_count}"
        )
    except Exception as e:
        logger.error(f"Ошибка при рассылке: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при рассылке")

    await state.clear()
