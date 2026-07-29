"""Общие обработчики — навигация, fallback, ошибки"""
import logging

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import ADMIN_IDS
from app.keyboards.main import get_main_menu_keyboard
from app.handlers.user_handlers import _get_cart_count
from app.utils.safe_edit import safe_edit_text

logger = logging.getLogger(__name__)
common_router = Router()


@common_router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    """Вернуться в главное меню"""
    user_id = callback.from_user.id
    is_admin = user_id in ADMIN_IDS
    cart_count = await _get_cart_count(user_id)

    await safe_edit_text(
        callback,
        "🏠 <b>Главное меню</b>",
        reply_markup=get_main_menu_keyboard(is_admin, cart_count > 0),
        parse_mode=ParseMode.HTML
    )


@common_router.callback_query()
async def fallback_callback(callback: CallbackQuery):
    """Fallback для неизвестных callback — предупреждение"""
    if callback.data and \
       not callback.data.startswith("dish_") and \
       not callback.data.startswith("add_to_cart_") and \
       not callback.data.startswith("favorite_") and \
       not callback.data.startswith("diet_toggle_") and \
       not callback.data.startswith("quick_order_") and \
       not callback.data.startswith("admin_dish_delete_") and \
       not callback.data.startswith("use_points_") and \
       not callback.data.startswith("toggle_slot_") and \
       not callback.data.startswith("reserve_") and \
       not callback.data.startswith("admin_reserve_") and \
       not callback.data.startswith("loc_") and \
       not callback.data.startswith("seats_") and \
       not callback.data.startswith("date_") and \
       not callback.data.startswith("time_") and \
       not callback.data.startswith("table_") and \
       not callback.data.startswith("admin_reservations") and \
       not callback.data.startswith("constructor") and \
       not callback.data.startswith("tmpl_") and \
       not callback.data.startswith("ing_") and \
       not callback.data.startswith("admin_check_") and \
       not callback.data.startswith("admin_order_") and \
       not callback.data.startswith("admin_payment_checks") and \
       not callback.data.startswith("admin_orders"):
        logger.warning(f"Неизвестный callback: {callback.data}")
        await callback.answer("Действие не распознано", show_alert=False)
