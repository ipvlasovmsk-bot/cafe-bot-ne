"""Админ-обработчики бронирований столиков"""
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import ADMIN_IDS
from app.database import get_db
from app.states import AdminStates
from app.services.reservations import ReservationService
from app.models import ReservationStatus
from app.keyboards.main import (
    get_back_keyboard, get_admin_reservation_keyboard
)

logger = logging.getLogger(__name__)
admin_reservation_router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _format_date_display(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        return f"{dt.strftime('%d.%m')} ({weekdays[dt.weekday()]})"
    except ValueError:
        return date_str


def _get_status_emoji(status: str) -> str:
    return {
        "pending": "⏳",
        "confirmed": "✅",
        "rejected": "❌",
        "cancelled": "🚫",
        "completed": "✔️",
        "no_show": "😔",
    }.get(status, "❓")


# ==================== СПИСОК БРОНИРОВАНИЙ ====================

@admin_reservation_router.callback_query(F.data == "admin_reservations")
async def admin_reservations(callback: CallbackQuery):
    """Список всех бронирований"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    async with get_db() as db:
        service = ReservationService(db)
        reservations = await service.get_all_reservations(limit=20)

    if not reservations:
        await callback.message.edit_text(
            "📅 <b>Бронирований пока нет</b>",
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    # Группируем по статусам
    pending = [r for r in reservations if r["status"] == "pending"]
    others = [r for r in reservations if r["status"] != "pending"]

    text = "📅 <b>Управление бронированиями</b>\n\n"

    if pending:
        text += f"⏳ <b>Ожидает подтверждения: {len(pending)}</b>\n"
        for r in pending[:5]:
            text += f"  • #{r['id']} | {r.get('first_name', '')} | "
            text += f"{_format_date_display(r['reservation_date'])} {r['reservation_time']} | "
            text += f"{r.get('table_name', '?')}\n"
        text += "\n"

    if others:
        text += f"📋 <b>Остальные ({len(others)})</b>\n"
        for r in others[:5]:
            status_icon = _get_status_emoji(r["status"])
            text += f"  {status_icon} #{r['id']} | "
            text += f"{_format_date_display(r['reservation_date'])} {r['reservation_time']} | "
            text += f"{r.get('first_name', '')}\n"

    # Кнопки навигации
    builder = InlineKeyboardBuilder()
    if pending:
        builder.button(text="⏳ Ожидает подтверждения", callback_data="admin_reserve_pending")
    builder.button(text="✅ Подтверждённые", callback_data="admin_reserve_confirmed")
    builder.button(text="📋 Все бронирования", callback_data="admin_reserve_all")
    builder.button(text="🔙 Назад", callback_data="admin_panel")
    builder.adjust(1)

    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ==================== ФИЛЬТРЫ ====================

STATUS_FILTER_MAP = {
    "admin_reserve_pending": "pending",
    "admin_reserve_confirmed": "confirmed",
    "admin_reserve_all": None,
}


@admin_reservation_router.callback_query(
    F.data.in_(["admin_reserve_pending", "admin_reserve_confirmed", "admin_reserve_all"])
)
async def filter_reservations(callback: CallbackQuery):
    """Фильтрация бронирований по статусу"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    filter_key = callback.data
    status_filter = STATUS_FILTER_MAP.get(filter_key)

    async with get_db() as db:
        service = ReservationService(db)
        reservations = await service.get_all_reservations(status=status_filter, limit=30)

    if not reservations:
        status_name = {"pending": "ожидающих", "confirmed": "подтверждённых"}.get(status_filter, "")
        await callback.message.edit_text(
            f"📅 <b>{status_name.capitalize()} бронирований не найдено</b>",
            reply_markup=get_back_keyboard("admin_panel"),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    text = f"📅 <b>Бронирования ({len(reservations)})</b>\n\n"

    for r in reservations[:15]:
        status_icon = _get_status_emoji(r["status"])
        date_display = _format_date_display(r["reservation_date"])
        guest_name = r.get("first_name", r.get("guest_name", "?"))

        text += (
            f"{status_icon} <b>#{r['id']}</b> | {guest_name}\n"
            f"   📅 {date_display} {r['reservation_time']} | "
            f"📍 {r.get('table_name', '?')} | 👥 {r['guest_count']}\n"
        )
        if r.get("special_requests"):
            text += f"   💬 <i>{r['special_requests']}</i>\n"
        text += "\n"

    # Кнопки для каждого бронирования
    builder = InlineKeyboardBuilder()
    for r in reservations[:10]:
        if r["status"] == "pending":
            builder.button(
                text=f"#{r['id']} — {_format_date_display(r['reservation_date'])} {r['reservation_time']}",
                callback_data=f"admin_reserve_detail_{r['id']}"
            )
    builder.button(text="🔙 Назад", callback_data="admin_reservations")
    builder.adjust(1)

    await callback.message.edit_text(
        text,
        reply_markup=builder.as_markup(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ==================== ДЕТАЛИ БРОНИРОВАНИЯ ====================

@admin_reservation_router.callback_query(F.data.startswith("admin_reserve_detail_"))
async def reservation_detail(callback: CallbackQuery):
    """Детали бронирования для админа"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    reservation_id = int(callback.data.split("_")[-1])

    async with get_db() as db:
        service = ReservationService(db)
        reservation = await service.get_reservation(reservation_id)

    if not reservation:
        await callback.message.edit_text("❌ Бронирование не найдено.")
        await callback.answer()
        return

    date_display = _format_date_display(reservation["reservation_date"])
    status_text = {
        "pending": "⏳ Ожидает подтверждения",
        "confirmed": "✅ Подтверждено",
        "rejected": "❌ Отклонено",
        "cancelled": "🚫 Отменено",
        "completed": "✔️ Завершено",
        "no_show": "😔 Не пришли",
    }.get(reservation["status"], reservation["status"])

    text = (
        f"📅 <b>Бронирование #{reservation_id}</b>\n\n"
        f"📍 <b>{reservation.get('table_name', '?')}</b>\n"
        f"📅 {date_display} в {reservation['reservation_time']}\n"
        f"👥 Гостей: {reservation['guest_count']}\n\n"
        f"👤 <b>Гость:</b> {reservation['guest_name']}\n"
        f"📞 <b>Телефон:</b> {reservation['guest_phone']}\n"
        f"🆔 <b>Пользователь:</b> {reservation['user_id']}\n"
        f"📝 <b>Статус:</b> {status_text}\n"
    )

    if reservation.get("special_requests"):
        text += f"💬 <b>Пожелания:</b> {reservation['special_requests']}\n"
    if reservation.get("admin_comment"):
        text += f"📝 <b>Комментарий админа:</b> {reservation['admin_comment']}\n"

    if reservation["status"] == "pending":
        keyboard = get_admin_reservation_keyboard(reservation_id)
    else:
        keyboard = get_back_keyboard("admin_reservations")

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ==================== ПОДТВЕРЖДЕНИЕ / ОТКЛОНЕНИЕ ====================

@admin_reservation_router.callback_query(F.data.startswith("admin_reserve_confirm_"))
async def confirm_reservation(callback: CallbackQuery):
    """Подтвердить бронирование"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    reservation_id = int(callback.data.split("_")[-1])

    async with get_db() as db:
        service = ReservationService(db)
        reservation = await service.get_reservation(reservation_id)
        if reservation and reservation["status"] == "pending":
            await service.update_reservation_status(
                reservation_id, ReservationStatus.CONFIRMED
            )

    if not reservation:
        await callback.answer("Бронирование не найдено", show_alert=True)
        return

    date_display = _format_date_display(reservation["reservation_date"])

    await callback.message.edit_text(
        f"✅ <b>Бронирование #{reservation_id} подтверждено</b>\n\n"
        f"📍 {reservation.get('table_name', '?')}\n"
        f"📅 {date_display} в {reservation['reservation_time']}\n"
        f"👤 {reservation['guest_name']} | {reservation['guest_phone']}",
        reply_markup=get_back_keyboard("admin_reservations"),
        parse_mode=ParseMode.HTML
    )

    # Уведомить пользователя
    try:
        await callback.bot.send_message(
            reservation["user_id"],
            f"✅ <b>Бронирование подтверждено!</b>\n\n"
            f"📍 {reservation.get('table_name', '?')}\n"
            f"📅 {date_display} в {reservation['reservation_time']}\n"
            f"👥 Гостей: {reservation['guest_count']}\n\n"
            f"Ждём вас!",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.warning(f"Не удалось уведомить пользователя: {e}")

    await callback.answer("Подтверждено ✅")


@admin_reservation_router.callback_query(F.data.startswith("admin_reserve_reject_"))
async def reject_reservation(callback: CallbackQuery):
    """Отклонить бронирование"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    reservation_id = int(callback.data.split("_")[-1])

    async with get_db() as db:
        service = ReservationService(db)
        reservation = await service.get_reservation(reservation_id)
        if reservation and reservation["status"] == "pending":
            await service.update_reservation_status(
                reservation_id, ReservationStatus.REJECTED
            )

    if not reservation:
        await callback.answer("Бронирование не найдено", show_alert=True)
        return

    date_display = _format_date_display(reservation["reservation_date"])

    await callback.message.edit_text(
        f"❌ <b>Бронирование #{reservation_id} отклонено</b>\n\n"
        f"📍 {reservation.get('table_name', '?')}\n"
        f"📅 {date_display} в {reservation['reservation_time']}\n"
        f"👤 {reservation['guest_name']}",
        reply_markup=get_back_keyboard("admin_reservations"),
        parse_mode=ParseMode.HTML
    )

    # Уведомить пользователя
    try:
        await callback.bot.send_message(
            reservation["user_id"],
            f"❌ <b>Бронирование отклонено</b>\n\n"
            f"📍 {reservation.get('table_name', '?')}\n"
            f"📅 {date_display} в {reservation['reservation_time']}\n\n"
            f"К сожалению, мы не можем подтвердить вашу бронь.\n"
            f"Попробуйте другое время или свяжитесь с кафе.",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.warning(f"Не удалось уведомить пользователя: {e}")

    await callback.answer("Отклонено ❌")


# ==================== КОММЕНТАРИЙ АДМИНА ====================

@admin_reservation_router.callback_query(F.data.startswith("admin_reserve_comment_"))
async def start_add_comment(callback: CallbackQuery, state: FSMContext):
    """Добавить комментарий к брони"""
    if not _is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён", show_alert=True)
        return

    reservation_id = int(callback.data.split("_")[-1])
    await state.set_state(AdminStates.reservation_comment)
    await state.update_data(comment_reservation_id=reservation_id)

    await callback.message.edit_text(
        "💬 <b>Добавить комментарий</b>\n\n"
        f"Бронирование #{reservation_id}\n"
        "Напишите комментарий для пользователя:",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@admin_reservation_router.message(AdminStates.reservation_comment)
async def process_admin_comment(message: Message, state: FSMContext):
    """Обработка комментария админа"""
    if not _is_admin(message.from_user.id):
        return

    data = await state.get_data()
    reservation_id = data.get("comment_reservation_id")

    if not reservation_id:
        await message.answer("❌ Ошибка: не указано бронирование.")
        await state.clear()
        return

    comment = message.text.strip()

    async with get_db() as db:
        service = ReservationService(db)
        reservation = await service.get_reservation(reservation_id)
        if reservation:
            await service.update_reservation_status(
                reservation_id,
                ReservationStatus(reservation["status"]),
                admin_comment=comment
            )

            # Уведомить пользователя
            try:
                await message.bot.send_message(
                    reservation["user_id"],
                    f"📝 <b>Комментарий к бронированию</b>\n\n"
                    f"📍 {reservation.get('table_name', '?')}\n"
                    f"📅 {_format_date_display(reservation['reservation_date'])} "
                    f"в {reservation['reservation_time']}\n\n"
                    f"💬 {comment}",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить комментарий: {e}")

    await message.answer(
        f"✅ Комментарий добавлен к бронированию #{reservation_id}"
    )
    await state.clear()
