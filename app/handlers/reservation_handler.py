"""Обработчики бронирования столиков — пользовательская часть"""
import logging
from datetime import datetime, timedelta

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import default_state
from aiogram.types import CallbackQuery, Message
from aiogram.enums import ParseMode

from app.config import ADMIN_IDS
from app.database import get_db
from app.states import UserStates
from app.services.reservations import ReservationService, RESERVATION_TIME_SLOTS
from app.services.reservations import LOCATION_NAMES
from app.models import ReservationStatus, TableLocation
from app.keyboards.main import (
    get_main_menu_keyboard, get_reservation_menu_keyboard,
    get_location_filter_keyboard, get_seats_keyboard,
    get_date_keyboard, get_time_keyboard, get_table_keyboard,
    get_reservation_confirm_keyboard, get_back_keyboard,
)

logger = logging.getLogger(__name__)
reservation_router = Router()


# Утилиты
def _format_date_display(date_str: str) -> str:
    """Формат даты для отображения"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        return f"{dt.strftime('%d.%m')} ({weekdays[dt.weekday()]})"
    except ValueError:
        return date_str


def _get_next_14_days() -> list[str]:
    """Список дат на ближайшие 14 дней в формате YYYY-MM-DD"""
    today = datetime.now()
    days = []
    for i in range(14):
        d = today + timedelta(days=i)
        days.append(d.strftime("%Y-%m-%d"))
    return days


def _get_status_display(status: str) -> str:
    """Статус бронирования — человекочитаемый"""
    return {
        "pending": "⏳ Ожидает подтверждения",
        "confirmed": "✅ Подтверждено",
        "rejected": "❌ Отклонено",
        "cancelled": "🚫 Отменено вами",
        "completed": "✔️ Завершено",
        "no_show": "😔 Не пришли",
    }.get(status, status)


# ==================== ГЛАВНОЕ МЕНЮ БРОНИРОВАНИЯ ====================

@reservation_router.callback_query(F.data == "reservation")
async def reservation_menu(callback: CallbackQuery):
    """Меню бронирования"""
    await callback.message.edit_text(
        "📅 <b>Бронирование столика</b>\n\n"
        "Забронируйте столик в кафе на удобное время.\n"
        "Бронирование требует подтверждения администратором.",
        reply_markup=get_reservation_menu_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ==================== МОИ БРОНИРОВАНИЯ ====================

@reservation_router.callback_query(F.data == "reserve_my")
async def my_reservations(callback: CallbackQuery):
    """Показать бронирования пользователя"""
    user_id = callback.from_user.id

    async with get_db() as db:
        service = ReservationService(db)
        reservations = await service.get_user_reservations(user_id, limit=10)

    if not reservations:
        await callback.message.edit_text(
            "📋 <b>У вас пока нет бронирований</b>\n\n"
            "Забронируйте столик — это просто!",
            reply_markup=get_reservation_menu_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    text = "📋 <b>Ваши бронирования</b>\n\n"
    for r in reservations[:5]:
        table_name = r.get("table_name", f"Столик #{r['table_id']}")
        date_display = _format_date_display(r["reservation_date"])
        status = _get_status_display(r["status"])

        text += (
            f"📍 <b>{table_name}</b>\n"
            f"📅 {date_display} в {r['reservation_time']}\n"
            f"👥 Гостей: {r['guest_count']} | {status}"
        )
        if r.get("admin_comment"):
            text += f"\n💬 <i>{r['admin_comment']}</i>"
        text += "\n\n"

    # Проверяем, изменилось ли сообщение
    try:
        await callback.message.edit_text(
            text,
            reply_markup=get_back_keyboard("main"),
            parse_mode=ParseMode.HTML
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            # Сообщение не изменилось — игнорируем
            pass
        else:
            logger.warning(f"Ошибка редактирования сообщения: {e}")
            await callback.message.answer(
                text,
                reply_markup=get_back_keyboard("main"),
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        logger.warning(f"Не удалось редактировать сообщение: {e}")
        await callback.message.answer(
            text,
            reply_markup=get_back_keyboard("main"),
            parse_mode=ParseMode.HTML
        )
    await callback.answer()


# ==================== НОВОЕ БРОНИРОВАНИЕ — ШАГ 1: ЛОКАЦИЯ ====================

@reservation_router.callback_query(F.data == "reserve_new")
async def start_reservation(callback: CallbackQuery, state: FSMContext):
    """Начать новое бронирование — выбор локации"""
    await state.set_state(UserStates.reservation_select_date)
    await state.update_data(reservation_step="location")

    await callback.message.edit_text(
        "🏠 <b>Выберите зону</b>\n\n"
        "Где бы вы хотели сидеть?",
        reply_markup=get_location_filter_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ==================== ШАГ 2: КОЛИЧЕСТВО ГОСТЕЙ ====================

LOCATION_MAP = {
    "loc_any": None,
    "loc_window": TableLocation.WINDOW,
    "loc_hall": TableLocation.HALL,
    "loc_corner": TableLocation.CORNER,
    "loc_vip": TableLocation.VIP,
    "loc_terrace": TableLocation.TERRACE,
}


@reservation_router.callback_query(F.data.startswith("loc_"))
async def select_location(callback: CallbackQuery, state: FSMContext):
    """Выбрана зона — просим кол-во гостей"""
    location_key = callback.data  # loc_window и т.д.
    await state.update_data(reservation_location=location_key)
    await state.set_state(UserStates.reservation_select_time)  # временно, для FSM

    await callback.message.edit_text(
        "👥 <b>Сколько будет гостей?</b>",
        reply_markup=get_seats_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ==================== ШАГ 3: ДАТА ====================

@reservation_router.callback_query(F.data.startswith("seats_"))
async def select_seats(callback: CallbackQuery, state: FSMContext):
    """Выбрано кол-во гостей — выбираем дату"""
    try:
        guest_count = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return
    await state.update_data(reservation_guests=guest_count)
    await state.set_state(UserStates.reservation_select_table)

    dates = _get_next_14_days()
    date_options = [_format_date_display(d) for d in dates]

    await callback.message.edit_text(
        "📅 <b>Выберите дату</b>\n\n"
        f"Гостей: {guest_count}",
        reply_markup=get_date_keyboard(dates, "Апрель 2026"),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ==================== ШАГ 4: ВРЕМЯ ====================

@reservation_router.callback_query(F.data.startswith("date_"))
async def select_date(callback: CallbackQuery, state: FSMContext):
    """Выбрана дата — выбираем время"""
    try:
        date_str = callback.data.rsplit("_", 1)[1]
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return
    await state.update_data(reservation_date=date_str)

    # Покажем все слоты — конкретный столик ещё не выбран
    await callback.message.edit_text(
        f"🕐 <b>Выберите время</b>\n\n"
        f"📅 {_format_date_display(date_str)}\n\n"
        "Доступное время может измениться после выбора столика.",
        reply_markup=get_time_keyboard(RESERVATION_TIME_SLOTS[:]),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ==================== ШАГ 5: СТОЛИК ====================

@reservation_router.callback_query(F.data.startswith("time_"))
async def select_time(callback: CallbackQuery, state: FSMContext):
    """Выбрано время — показываем доступные столики"""
    try:
        time_str = callback.data.rsplit("_", 1)[1]
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return
    data = await state.get_data()
    date_str = data.get("reservation_date")
    location_key = data.get("reservation_location", "loc_any")
    guest_count = data.get("reservation_guests", 2)

    location = LOCATION_MAP.get(location_key)
    min_seats = guest_count

    async with get_db() as db:
        service = ReservationService(db)
        tables = await service.get_available_tables(date_str, time_str, min_seats=min_seats)

    if not tables:
        await callback.message.edit_text(
            f"😔 <b>Нет свободных столиков</b>\n\n"
            f"📅 {_format_date_display(date_str)} в {time_str}\n"
            f"👥 Гостей: {guest_count}\n\n"
            "Попробуйте другое время или дату.",
            reply_markup=get_back_keyboard("reserve_new"),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    await state.update_data(reservation_time=time_str)

    await callback.message.edit_text(
        f"📍 <b>Выберите столик</b>\n\n"
        f"📅 {_format_date_display(date_str)} в {time_str}\n"
        f"👥 Гостей: {guest_count}",
        reply_markup=get_table_keyboard(tables),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@reservation_router.callback_query(F.data == "no_slots")
async def no_slots(callback: CallbackQuery):
    """Нет слотов"""
    await callback.message.edit_text(
        "😔 К сожалению, все столики заняты.\n"
        "Попробуйте выбрать другую дату или время.",
        reply_markup=get_back_keyboard("reserve_new"),
    )
    await callback.answer()


# ==================== ШАГ 6: ДАННЫЕ ГОСТЯ ====================

@reservation_router.callback_query(F.data.startswith("table_"))
async def select_table(callback: CallbackQuery, state: FSMContext):
    """Выбран столик — запрашиваем имя и телефон"""
    try:
        table_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return
    await state.update_data(reservation_table_id=table_id)
    await state.set_state(UserStates.reservation_guest_info)

    await callback.message.edit_text(
        "👤 <b>Укажите ваши данные</b>\n\n"
        "Напишите <b>имя</b> и <b>номер телефона</b> в формате:\n"
        "<code>Иван +79991234567</code>\n\n"
        "Или нажмите «Назад», чтобы выбрать другой столик.",
        reply_markup=get_back_keyboard("reserve_new"),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@reservation_router.message(UserStates.reservation_guest_info)
async def process_guest_info(message: Message, state: FSMContext):
    """Обработка имени и телефона"""
    text = message.text.strip()

    # Простая проверка — хотя бы 2 слова или имя + телефон
    parts = text.split()
    if len(parts) < 2:
        await message.answer(
            "⚠️ Пожалуйста, укажите имя и телефон.\n"
            "Пример: <code>Иван +79991234567</code>",
            parse_mode=ParseMode.HTML
        )
        return

    guest_name = parts[0]
    guest_phone = " ".join(parts[1:])

    await state.update_data(reservation_guest_name=guest_name)
    await state.update_data(reservation_guest_phone=guest_phone)
    await state.set_state(UserStates.reservation_requests)

    await message.answer(
        "💬 <b>Особые пожелания</b>\n\n"
        "Есть ли у вас особые пожелания?\n"
        "Напишите их или отправьте «-» если нет.\n\n"
        "<i>Пример: нужен детский стульчик, окно у стола</i>",
        reply_markup=get_back_keyboard("reserve_new"),
        parse_mode=ParseMode.HTML
    )


@reservation_router.message(UserStates.reservation_requests)
async def process_requests(message: Message, state: FSMContext):
    """Обработка пожеланий — финальный шаг"""
    text = message.text.strip()
    special_requests = "" if text == "-" else text

    await state.update_data(reservation_requests=special_requests)
    await state.set_state(UserStates.reservation_confirm)

    # Создаём бронирование в БД
    data = await state.get_data()
    user_id = message.from_user.id

    async with get_db() as db:
        service = ReservationService(db)
        reservation_id = await service.create_reservation(
            user_id=user_id,
            table_id=data["reservation_table_id"],
            date=data["reservation_date"],
            time=data["reservation_time"],
            guest_count=data["reservation_guests"],
            guest_name=data["reservation_guest_name"],
            guest_phone=data["reservation_guest_phone"],
            special_requests=special_requests,
        )
        # Получим данные для отображения
        reservation = await service.get_reservation(reservation_id)

    if not reservation:
        await message.answer("❌ Произошла ошибка при создании бронирования.")
        return

    table_name = reservation.get("table_name", f"Столик #{reservation['table_id']}")
    date_display = _format_date_display(reservation["reservation_date"])

    await message.answer(
        f"📋 <b>Проверьте бронирование</b>\n\n"
        f"📍 <b>{table_name}</b>\n"
        f"📅 {date_display} в {reservation['reservation_time']}\n"
        f"👥 Гостей: {reservation['guest_count']}\n"
        f"👤 {reservation['guest_name']} | {reservation['guest_phone']}\n"
        f"💬 Пожелания: {special_requests or 'нет'}\n\n"
        "Подтвердить бронирование?",
        reply_markup=get_reservation_confirm_keyboard(reservation_id),
        parse_mode=ParseMode.HTML
    )


# ==================== ШАГ 7: ПОДТВЕРЖДЕНИЕ ====================

@reservation_router.callback_query(F.data.startswith("reserve_confirm_"))
async def confirm_reservation(callback: CallbackQuery, state: FSMContext):
    """Подтверждение бронирования"""
    try:
        reservation_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return

    async with get_db() as db:
        service = ReservationService(db)
        reservation = await service.get_reservation(reservation_id)

    if not reservation:
        await callback.message.edit_text("❌ Бронирование не найдено.")
        await callback.answer()
        return

    table_name = reservation.get("table_name", f"Столик #{reservation['table_id']}")
    date_display = _format_date_display(reservation["reservation_date"])

    await callback.message.edit_text(
        f"✅ <b>Бронирование отправлено!</b>\n\n"
        f"📍 <b>{table_name}</b>\n"
        f"📅 {date_display} в {reservation['reservation_time']}\n"
        f"👥 Гостей: {reservation['guest_count']}\n\n"
        "Администратор подтвердит вашу бронировку.\n"
        "Мы уведомим вас о результате.",
        reply_markup=get_back_keyboard("main"),
        parse_mode=ParseMode.HTML
    )

    # Уведомить админов
    try:
        bot = callback.bot
        from app.config import ADMIN_IDS
        for admin_id in ADMIN_IDS:
            await bot.send_message(
                admin_id,
                f"📅 <b>Новое бронирование!</b>\n\n"
                f"📍 {table_name}\n"
                f"📅 {date_display} в {reservation['reservation_time']}\n"
                f"👥 Гостей: {reservation['guest_count']}\n"
                f"👤 {reservation['guest_name']} | {reservation['guest_phone']}\n"
                f"💬 Пожелания: {reservation.get('special_requests', 'нет')}\n"
                f"🆔 Пользователь: {reservation['user_id']}\n\n"
                f"ID бронирования: <code>{reservation_id}</code>",
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        logger.warning(f"Не удалось уведомить админов: {e}")

    await state.clear()
    await callback.answer()


@reservation_router.callback_query(F.data == "reserve_cancel")
async def cancel_reservation_flow(callback: CallbackQuery, state: FSMContext):
    """Отмена процесса бронирования"""
    await state.clear()
    await callback.message.edit_text(
        "📅 Бронирование отменено.",
        reply_markup=get_main_menu_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()
