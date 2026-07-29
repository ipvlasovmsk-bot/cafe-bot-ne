"""Обработчики для управления заказами администратором"""
import logging
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import ADMIN_IDS, TIMEZONE_OFFSET
from app.database import get_db
from app.states import AdminStates
from app.keyboards.main import get_back_keyboard
from app.utils.thai_time import format_price, format_thailand_time
from app.config import CURRENCY_SYMBOL

logger = logging.getLogger(__name__)
admin_order_router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@admin_order_router.callback_query(F.data == "admin_orders")
async def admin_orders_list(callback: CallbackQuery, bot: Bot):
    """Список заказов с детализацией"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT o.id, o.user_id, o.total_price, o.status, o.created_at, o.address, o.estimated_ready_time, "
            "u.first_name, u.username, o.courier_id "
            "FROM orders o "
            "LEFT JOIN users u ON o.user_id = u.user_id "
            "ORDER BY o.created_at DESC LIMIT 30"
        )
        orders = await cursor.fetchall()

    status_icons = {
        'new': '🆕',
        'payment_pending': '💳',
        'accepted': '✅',
        'cooking': '🍳',
        'ready': '📦',
        'courier_assigned': '🚚',
        'delivered': '✅'
    }

    text = "📋 <b>Управление заказами</b>\n\n"
    for order in orders:
        order_id, user_id, total, status, created, address, est_ready, first_name, username, courier_id = order
        date_str = format_thailand_time(datetime.fromisoformat(created), "%d.%m %H:%M")
        user_info = f"@{username}" if username else f"{first_name}"
        icon = status_icons.get(status, '❓')
        
        text += f"{icon} <b>Заказ #{order_id}</b> | {user_info}\n"
        text += f"   💰 {format_price(total)} | Статус: {status}\n"
        if address:
            # Обрезаем длинный адрес
            if len(address) > 50:
                text += f"   📍 {address[:50]}...\n"
            else:
                text += f"   📍 {address}\n"
        if est_ready and status in ['cooking', 'ready', 'courier_assigned']:
            # Форматируем время: если полное ISO - берём только ЧЧ:ММ
            try:
                if 'T' in str(est_ready):
                    ready_time_str = format_thailand_time(datetime.fromisoformat(est_ready), "%H:%M")
                else:
                    ready_time_str = str(est_ready)
            except:
                ready_time_str = str(est_ready)
            text += f"   ⏰ Готовность: {ready_time_str}\n"
        if courier_id and status in ['courier_assigned', 'delivered']:
            text += f"   🚚 Курьер: ID {courier_id}\n"
        text += f"   🕒 {date_str}\n\n"

    if not orders:
        text += "Заказов пока нет."

    builder = InlineKeyboardBuilder()
    for order in orders:
        order_id = order[0]
        status = order[3]
        builder.button(text=f"{status_icons.get(status, '❓')} #{order_id}", callback_data=f"admin_order_view_{order_id}")
    builder.button(text="🔙 Назад", callback_data="admin_panel")
    builder.adjust(2)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@admin_order_router.callback_query(F.data.startswith("admin_order_view_"))
async def admin_order_view(callback: CallbackQuery, bot: Bot):
    """Просмотр деталей заказа"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        order_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT o.id, o.user_id, o.items, o.total_price, o.status, o.created_at, o.address, "
            "o.lat, o.lon, o.delivery_time, o.estimated_ready_time, o.courier_id, "
            "u.first_name, u.username, u.phone "
            "FROM orders o "
            "LEFT JOIN users u ON o.user_id = u.user_id "
            "WHERE o.id = ?",
            (order_id,)
        )
        order = await cursor.fetchone()

        if not order:
            await callback.answer("Заказ не найден", show_alert=True)
            return

        (order_id, user_id, items, total, status, created, address, 
         lat, lon, delivery_time, est_ready, courier_id,
         first_name, username, phone) = order

    date_str = format_thailand_time(datetime.fromisoformat(created), "%d.%m %H:%M")
    user_info = f"@{username}" if username else f"{first_name}"

    text = f"📋 <b>Заказ #{order_id}</b>\n\n"
    text += f"👤 Пользователь: {user_info}\n"
    text += f"📱 Телефон: {phone}\n"
    if address:
        text += f"📍 Адрес: {address}\n"
    if lat and lon:
        text += f"🗺️ Координаты: {lat:.6f}, {lon:.6f}\n"
    text += f"💰 Сумма: {format_price(total)}\n"
    text += f"📊 Статус: {status}\n"
    text += f"🕒 Создан: {date_str}\n"
    if est_ready:
        # Форматируем время: если полное ISO - берём только ЧЧ:ММ
        try:
            if 'T' in str(est_ready):
                ready_time_str = format_thailand_time(datetime.fromisoformat(est_ready), "%H:%M")
            else:
                ready_time_str = str(est_ready)
        except:
            ready_time_str = str(est_ready)
        text += f"⏰ Ожидаемая готовность: {ready_time_str}\n"
    if delivery_time:
        text += f"🚚 Время доставки: {delivery_time}\n"

    # Состав заказа
    try:
        import json
        items_data = json.loads(items)
        text += f"\n📦 <b>Состав заказа:</b>\n"
        for item in items_data:
            text += f"• {item.get('dish_name', 'Блюдо')} — {format_price(item.get('base_price', 0))}\n"
            if item.get('ingredients'):
                text += f"  + {item.get('ingredients')}\n"
    except:
        text += f"\n📦 Состав: {items}\n"

    builder = InlineKeyboardBuilder()
    
    # Кнопки управления статусами
    if status == 'payment_pending':
        builder.button(text="✅ Принять чек", callback_data=f"admin_check_accept_{order_id}")
        builder.button(text="❌ Отклонить чек", callback_data=f"admin_check_reject_{order_id}")
    elif status == 'accepted':
        builder.button(text="🍳 Начать приготовление", callback_data=f"admin_order_cooking_{order_id}")
    elif status == 'cooking':
        ready_time = (datetime.now() + timedelta(minutes=40)).strftime("%H:%M")
        text += f"\n<i>Нажмите, чтобы отметить готовность и указать время:</i>\n"
        builder.button(text="✅ Заказ готов", callback_data=f"admin_order_ready_{order_id}_{ready_time}")
    elif status == 'ready':
        builder.button(text="🚚 Передать курьеру", callback_data=f"admin_order_courier_{order_id}")
    elif status == 'courier_assigned':
        builder.button(text="✅ Подтвердить доставку", callback_data=f"admin_order_delivered_{order_id}")
        builder.button(text="📸 Фото курьера", callback_data=f"admin_order_courier_photo_{order_id}")
    
    builder.button(text="❌ Удалить заказ", callback_data=f"admin_order_delete_{order_id}")
    builder.button(text="🔙 Назад к списку", callback_data="admin_orders")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)


@admin_order_router.callback_query(F.data.startswith("admin_order_cooking_"))
async def admin_order_cooking(callback: CallbackQuery, bot: Bot):
    """Перевод заказа в статус 'готовится'"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        order_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT user_id, total_price FROM orders WHERE id = ?",
            (order_id,)
        )
        order = await cursor.fetchone()

        if not order:
            await callback.answer("Заказ не найден", show_alert=True)
            return

        user_id, total_price = order

        # Устанавливаем время готовности (40 минут от сейчас)
        ready_time = datetime.now() + timedelta(minutes=40)
        est_ready_str = format_thailand_time(ready_time, "%H:%M")

        await db.execute(
            "UPDATE orders SET status = 'cooking', estimated_ready_time = ?, updated_at = ? WHERE id = ?",
            (est_ready_str, datetime.now().isoformat(), order_id)
        )

    # Уведомляем клиента
    try:
        text = (
            "🍳 <b>Ваш заказ готовится!</b>\n\n"
            f"Заказ #{order_id} передан на кухню.\n"
            f"Время приготовления: ~40 минут.\n"
            f"Ожидаемая готовность: <b>{est_ready_str}</b>\n\n"
            "Следите за статусом в разделе 'Мои заказы'."
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="📦 Мои заказы", callback_data="my_orders")
        builder.adjust(1)

        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления пользователя: {e}")

    await callback.answer("✅ Заказ передан в приготовление", show_alert=False)
    await admin_order_view(callback, bot)


@admin_order_router.callback_query(F.data.startswith("admin_order_ready_"))
async def admin_order_ready(callback: CallbackQuery, bot: Bot):
    """Перевод заказа в статус 'готов'"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    parts = callback.data.split("_")
    try:
        order_id = int(parts[3])
        ready_time = parts[4] if len(parts) > 4 else format_thailand_time(datetime.now(), "%H:%M")
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT user_id FROM orders WHERE id = ?",
            (order_id,)
        )
        order = await cursor.fetchone()

        if not order:
            await callback.answer("Заказ не найден", show_alert=True)
            return

        user_id = order[0]

        await db.execute(
            "UPDATE orders SET status = 'ready', actual_ready_time = ?, updated_at = ? WHERE id = ?",
            (ready_time, datetime.now().isoformat(), order_id)
        )

    # Уведомляем клиента
    try:
        text = (
            "✅ <b>Ваш заказ готов!</b>\n\n"
            f"Заказ #{order_id} передан курьеру.\n"
            f"Время готовности: {ready_time}\n\n"
            "Курьер уже выехал к вам! 🚚"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="📦 Мои заказы", callback_data="my_orders")
        builder.adjust(1)

        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления пользователя: {e}")

    await callback.answer("✅ Заказ готов, передан курьеру", show_alert=False)
    await admin_order_view(callback, bot)


@admin_order_router.callback_query(F.data.startswith("admin_order_courier_"))
async def admin_order_courier(callback: CallbackQuery, bot: Bot):
    """Назначение курьера и перевод в статус 'передан курьеру'"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        order_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return

    async with get_db() as db:
        # Получаем данные заказа
        cursor = await db.execute(
            "SELECT user_id, address, lat, lon FROM orders WHERE id = ?",
            (order_id,)
        )
        order = await cursor.fetchone()

        if not order:
            await callback.answer("Заказ не найден", show_alert=True)
            return

        user_id, address, lat, lon = order

        # Получаем свободного курьера
        cursor = await db.execute(
            "SELECT id, name FROM couriers WHERE status = 'offline' LIMIT 1"
        )
        courier = await cursor.fetchone()

        courier_id = None
        courier_name = "Не назначен"
        if courier:
            courier_id, courier_name = courier
            # Обновляем статус курьера
            await db.execute(
                "UPDATE couriers SET status = 'busy', current_lat = ?, current_lon = ?, last_update = ? WHERE id = ?",
                (lat, lon, datetime.now().isoformat(), courier_id)
            )

        # Обновляем заказ
        await db.execute(
            "UPDATE orders SET status = 'courier_assigned', courier_id = ?, updated_at = ? WHERE id = ?",
            (courier_id, datetime.now().isoformat(), order_id)
        )

    # Уведомляем клиента
    try:
        # Расчет времени доставки (примерно 30 минут)
        delivery_time = format_thailand_time(datetime.now() + timedelta(minutes=30), "%H:%M")
        
        text = (
            "🚚 <b>Заказ передан курьеру!</b>\n\n"
            f"Заказ #{order_id} в пути.\n"
            f"Курьер: {courier_name}\n"
            f"⏰ Ожидаемое время доставки: ~30 минут\n"
            f"🕐 Будем у вас к: {delivery_time}\n\n"
            "Следите за статусом в разделе 'Мои заказы'! 📦"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="📦 Мои заказы", callback_data="my_orders")
        builder.adjust(1)

        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления пользователя: {e}")

    await callback.answer(f"✅ Курьер {courier_name} назначен", show_alert=False)
    await admin_order_view(callback, bot)


@admin_order_router.callback_query(F.data.startswith("admin_order_courier_photo_"))
async def admin_order_courier_photo(callback: CallbackQuery, state: FSMContext):
    """Запрос фото курьера"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        order_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return

    text = (
        "📸 <b>Фото курьера</b>\n\n"
        "Отправьте фото курьера с заказом для подтверждения доставки."
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=f"admin_order_view_{order_id}")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    await state.update_data(courier_photo_order_id=order_id)
    await state.set_state(AdminStates.courier_photo)


@admin_order_router.message(AdminStates.courier_photo, F.photo)
async def process_courier_photo(message: Message, state: FSMContext, bot: Bot):
    """Обработка фото курьера"""
    data = await state.get_data()
    order_id = data.get('courier_photo_order_id')

    if not order_id:
        await message.answer("Ошибка: заказ не найден")
        await state.clear()
        return

    # Получаем file_id фото
    photo = message.photo[-1]
    file_id = photo.file_id

    # Сохраняем file_id в заказ
    async with get_db() as db:
        await db.execute(
            "UPDATE orders SET courier_photo_file_id = ? WHERE id = ?",
            (file_id, order_id)
        )

        # Получаем данные заказа
        cursor = await db.execute(
            "SELECT user_id, lat, lon FROM orders WHERE id = ?",
            (order_id,)
        )
        order = await cursor.fetchone()
        user_id = order[0]
        lat, lon = order[1], order[2]

    # Отправляем фото клиенту
    try:
        text = (
            "🚚 <b>Ваш заказ в пути!</b>\n\n"
            "Курьер уже выехал к вам. Фото курьера ниже.\n\n"
            "Скоро будем у вас! ⏱️\n"
            f"📍 Адрес доставки: {lat:.4f}, {lon:.4f}"
        )

        await bot.send_photo(
            chat_id=user_id,
            photo=file_id,
            caption=text,
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка отправки фото клиенту: {e}")

    await message.answer("✅ Фото отправлено клиенту!")
    await state.clear()

    # Возвращаемся к просмотру заказа
    class FakeCallback:
        def __init__(self, message, order_id):
            self.message = message
            self.from_user = message.from_user
            self.data = f"admin_order_view_{order_id}"
        
        async def answer(self, *args, **kwargs):
            pass
    
    fake_callback = FakeCallback(message, order_id)
    await admin_order_view(fake_callback, bot)


@admin_order_router.callback_query(F.data.startswith("admin_order_delivered_"))
async def admin_order_delivered(callback: CallbackQuery, bot: Bot):
    """Подтверждение доставки"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        order_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return

    async with get_db() as db:
        # Получаем данные заказа
        cursor = await db.execute(
            "SELECT user_id, total_price FROM orders WHERE id = ?",
            (order_id,)
        )
        order = await cursor.fetchone()

        if not order:
            await callback.answer("Заказ не найден", show_alert=True)
            return

        user_id, total_price = order

        # Обновляем статус заказа
        await db.execute(
            "UPDATE orders SET status = 'delivered', updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), order_id)
        )

        # Обновляем статус курьера
        await db.execute(
            "UPDATE couriers SET status = 'offline', last_update = ? WHERE id IS NOT NULL",
            (datetime.now().isoformat(),)
        )

        # Начисляем баллы
        points = total_price // 10
        await db.execute(
            "UPDATE users SET loyalty_points = loyalty_points + ? WHERE user_id = ?",
            (points, user_id)
        )

    # Уведомляем клиента
    try:
        text = (
            "✅ <b>Заказ доставлен!</b>\n\n"
            f"Заказ #{order_id} успешно доставлен.\n"
            f"Сумма: {format_price(total_price)}\n"
            f"🎁 Начислено баллов: {points}\n\n"
            "Будем рады видеть вас снова! 😊"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="⭐ Оставить отзыв", callback_data=f"review_order_{order_id}")
        builder.button(text="🍽️ Сделать новый заказ", callback_data="menu")
        builder.adjust(1)

        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления пользователя: {e}")

    await callback.answer("✅ Заказ доставлен", show_alert=False)
    await admin_order_view(callback, bot)


@admin_order_router.callback_query(F.data.startswith("admin_order_delete_"))
async def admin_order_delete(callback: CallbackQuery, bot: Bot):
    """Удаление заказа"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        order_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return

    async with get_db() as db:
        # Получаем данные заказа
        cursor = await db.execute(
            "SELECT user_id FROM orders WHERE id = ?",
            (order_id,)
        )
        order = await cursor.fetchone()

        if not order:
            await callback.answer("Заказ не найден", show_alert=True)
            return

        user_id = order[0]

        # Удаляем заказ
        await db.execute("DELETE FROM orders WHERE id = ?", (order_id,))

    # Уведомляем клиента
    try:
        text = (
            f"❌ <b>Заказ отменён</b>\n\n"
            f"Заказ #{order_id} был удалён администратором.\n\n"
            f"Если это ошибка, свяжитесь с поддержкой."
        )

        await bot.send_message(
            chat_id=user_id,
            text=text
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления пользователя: {e}")

    await callback.answer("✅ Заказ удалён", show_alert=False)
    await admin_orders_list(callback, bot)
