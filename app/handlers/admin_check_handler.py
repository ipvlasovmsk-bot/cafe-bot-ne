"""Обработчики для администраторов - проверка чеков"""
import logging
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message, BufferedInputFile
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import ADMIN_IDS, CURRENCY_SYMBOL
from app.database import get_db
from app.states import AdminStates
from app.keyboards.main import get_back_keyboard
from app.utils.thai_time import format_price, format_thailand_time

logger = logging.getLogger(__name__)
admin_check_router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@admin_check_router.callback_query(F.data == "admin_payment_checks")
async def admin_payment_checks(callback: CallbackQuery, bot: Bot):
    """Список заказов с ожидающими чеками"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    await _show_payment_checks_list(callback, bot)


async def _show_payment_checks_list(callback: CallbackQuery | Message, bot: Bot):
    """Внутренняя функция для отображения списка чеков"""
    from aiogram.types import CallbackQuery
    
    is_callback = isinstance(callback, CallbackQuery)
    
    if is_callback:
        user_id = callback.from_user.id
    else:
        user_id = callback.from_user.id if callback.from_user else 0
    
    if not _is_admin(user_id):
        if is_callback:
            await callback.answer("Доступ запрещён", show_alert=True)
        return

    async with get_db() as db:
        cursor = await db.execute(
            "SELECT o.id, o.user_id, o.total_price, o.payment_check_path, o.created_at, "
            "u.first_name, u.username "
            "FROM orders o "
            "LEFT JOIN users u ON o.user_id = u.user_id "
            "WHERE o.status = 'payment_pending' "
            "ORDER BY o.created_at DESC"
        )
        checks = await cursor.fetchall()

    if not checks:
        text = "💳 <b>Проверка чеков</b>\n\nОжидающих чеков нет."
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 Назад", callback_data="admin_panel")
        
        try:
            if is_callback:
                await callback.message.edit_text(
                    text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML
                )
            else:
                await callback.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        except Exception:
            # Если сообщение содержит фото, отправляем новое текстовое сообщение
            if is_callback:
                await callback.message.answer(
                    text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML
                )
            else:
                await callback.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
        return

    text = "💳 <b>Ожидающие чеки оплаты</b>\n\n"
    for check in checks:
        order_id, user_id, total, check_path, created, first_name, username = check
        date_str = format_thailand_time(datetime.fromisoformat(created), "%d.%m %H:%M")
        user_info = f"@{username}" if username else f"{first_name}"
        text += f"📋 Заказ #{order_id} от {user_info} — {format_price(total)}\n"
        text += f"   📅 {date_str}\n\n"

    text += "Нажмите на заказ, чтобы проверить чек."

    builder = InlineKeyboardBuilder()
    for check in checks:
        order_id = check[0]
        user_id = check[1]
        total = check[2]
        text_label = f"💳 Заказ #{order_id} ({format_price(total)})"
        builder.button(text=text_label, callback_data=f"admin_check_view_{order_id}")
    builder.button(text="🔙 Назад", callback_data="admin_panel")
    builder.adjust(1)

    try:
        if is_callback:
            await callback.message.edit_text(
                text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML
            )
        else:
            await callback.answer(text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML)
    except Exception:
        # Если сообщение содержит фото, отправляем новое
        if is_callback:
            await callback.message.answer(
                text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML
            )


@admin_check_router.callback_query(F.data.startswith("admin_check_view_"))
async def admin_check_view(callback: CallbackQuery, bot: Bot):
    """Просмотр чека"""
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
            "SELECT o.id, o.user_id, o.total_price, o.payment_check_path, o.created_at, "
            "o.items, u.first_name, u.username "
            "FROM orders o "
            "LEFT JOIN users u ON o.user_id = u.user_id "
            "WHERE o.id = ? AND o.status = 'payment_pending'",
            (order_id,)
        )
        check = await cursor.fetchone()

        if not check:
            await callback.answer("Заказ не найден или чек уже проверен", show_alert=True)
            return

        order_id, user_id, total, check_path, created, items, first_name, username = check
        date_str = format_thailand_time(datetime.fromisoformat(created), "%d.%m %H:%M")
        user_info = f"@{username}" if username else f"{first_name}"

    text = (
        f"💳 <b>Проверка чека</b>\n\n"
        f"📋 Заказ #{order_id}\n"
        f"👤 Пользователь: {user_info} (ID: {user_id})\n"
        f"💰 Сумма: {format_price(total)}\n"
        f"📅 Дата: {date_str}\n\n"
        f"📦 Состав заказа:\n"
    )

    try:
        import json
        items_data = json.loads(items)
        for item in items_data:
            text += f"• {item.get('dish_name', 'Блюдо')} — {format_price(item.get('base_price', 0))}\n"
    except:
        text += f"• {items}\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Принять чек", callback_data=f"admin_check_accept_{order_id}")
    builder.button(text="❌ Отклонить чек", callback_data=f"admin_check_reject_{order_id}")
    builder.button(text="🔙 Назад к списку", callback_data="admin_payment_checks")
    builder.adjust(1)

    # Если есть фото чека, отправляем его
    if check_path:
        try:
            import os
            from pathlib import Path
            from aiogram.types import BufferedInputFile
            path = Path(check_path)
            if path.exists():
                # Отправляем фото чека
                await callback.message.answer_photo(
                    photo=BufferedInputFile.from_file(path),
                    caption=text,
                    reply_markup=builder.as_markup(),
                    parse_mode=ParseMode.HTML
                )
                return
        except Exception as e:
            logger.error(f"Ошибка отправки фото чека: {e}")

    # Если фото нет или ошибка, просто показываем текст
    try:
        await callback.message.edit_text(
            text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML
        )
    except Exception:
        # Если сообщение содержит фото, отправляем новое
        await callback.message.answer(
            text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML
        )


@admin_check_router.callback_query(F.data.startswith("admin_check_accept_"))
async def admin_check_accept(callback: CallbackQuery, bot: Bot):
    """Принятие чека"""
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
            "UPDATE orders SET status = 'accepted', updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), order_id)
        )

    # Уведомляем пользователя
    try:
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        
        text = (
            "✅ <b>Ваш заказ подтверждён!</b>\n\n"
            f"Заказ #{order_id} принят в обработку.\n"
            f"Мы начали приготовление ваших блюд.\n\n"
            f"Следите за статусом заказа в разделе 'Мои заказы'."
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 Главное меню", callback_data="back_to_main")
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

    await callback.answer("✅ Чек принят, заказ подтверждён", show_alert=False)
    
    # Возвращаемся к списку чеков
    try:
        await admin_payment_checks(callback, bot)
    except Exception as e:
        logger.error(f"Ошибка обновления списка чеков: {e}")
        fallback_builder = InlineKeyboardBuilder()
        fallback_builder.button(text="📋 Список чеков", callback_data="admin_payment_checks")
        await callback.message.answer(
            "✅ Чек принят",
            reply_markup=fallback_builder.as_markup()
        )


@admin_check_router.callback_query(F.data.startswith("admin_check_reject_"))
async def admin_check_reject(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Отклонение чека"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    try:
        order_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return

    text = (
        "❌ <b>Отклонение чека</b>\n\n"
        "Напишите причину отклонения (необязательно):\n\n"
        "<i>Например: Нечёткое фото, неверная сумма, не тот заказ...</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отменить", callback_data=f"admin_check_view_{order_id}")
    builder.adjust(1)

    try:
        await callback.message.edit_text(
            text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML
        )
    except Exception:
        # Если сообщение содержит фото, отправляем новое
        await callback.message.answer(
            text, reply_markup=builder.as_markup(), parse_mode=ParseMode.HTML
        )
    await state.update_data(reject_order_id=order_id)
    await state.set_state(AdminStates.reject_order)


@admin_check_router.message(AdminStates.reject_order, F.text)
async def process_reject_reason(message: Message, state: FSMContext, bot: Bot):
    """Обработка причины отклонения"""
    current_state = await state.get_state()
    if current_state != AdminStates.reject_order:
        return

    if not _is_admin(message.from_user.id):
        return

    data = await state.get_data()
    order_id = data.get('reject_order_id')

    if not order_id:
        await message.answer("Ошибка: заказ не найден")
        await state.clear()
        return

    reason = message.text.strip()

    async with get_db() as db:
        # Получаем данные заказа
        cursor = await db.execute(
            "SELECT user_id, total_price FROM orders WHERE id = ?",
            (order_id,)
        )
        order = await cursor.fetchone()

        if not order:
            await message.answer("Заказ не найден")
            await state.clear()
            return

        user_id, total_price = order

        # Удаляем заказ (чтобы пользователь мог оформить заново)
        await db.execute("DELETE FROM orders WHERE id = ?", (order_id,))

    # Уведомляем пользователя
    try:
        text = (
            "❌ <b>Чек отклонён</b>\n\n"
            f"Заказ #{order_id} был отменён.\n\n"
        )
        if reason and reason != "-":
            text += f"📝 Причина: {reason}\n\n"
        text += (
            "Пожалуйста, оформите заказ заново или свяжитесь с поддержкой.\n\n"
            "Извините за неудобства!"
        )

        builder = InlineKeyboardBuilder()
        builder.button(text="🏠 Главное меню", callback_data="back_to_main")
        builder.button(text="🍽️ Оформить заказ", callback_data="menu")
        builder.adjust(1)

        await bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=builder.as_markup(),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Ошибка уведомления пользователя: {e}")

    await state.clear()

    # Возвращаемся к списку чеков
    # Создаем фейковый callback для вызова функции
    class FakeCallback:
        def __init__(self, message):
            self.message = message
            self.from_user = message.from_user
            self.data = "admin_payment_checks"
        
        async def answer(self, *args, **kwargs):
            pass
    
    fake_callback = FakeCallback(message)
    await _show_payment_checks_list(fake_callback, bot)


# Добавляем кнопку в админ-панель
async def extend_admin_panel():
    """Функция для добавления кнопки чеков в админ-панель"""
    pass
