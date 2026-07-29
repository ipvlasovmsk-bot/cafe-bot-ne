"""Обработчики для загрузки чеков при оплате"""
import logging
import os
from datetime import datetime
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, PhotoSize
from aiogram.enums import ParseMode

from app.database import get_db
from app.states import UserStates
from app.keyboards.main import get_back_keyboard
from app.utils.safe_edit import safe_edit_text
from app.utils.thai_time import format_price

logger = logging.getLogger(__name__)
payment_check_router = Router()

# Директория для хранения чеков
CHECKS_DIR = Path("uploads/checks")
CHECKS_DIR.mkdir(parents=True, exist_ok=True)

# Глобальный bot для отправки уведомлений
bot: Bot | None = None


def set_bot_instance(b: Bot):
    """Установить экземпляр бота для уведомлений"""
    global bot
    bot = b


@payment_check_router.callback_query(F.data == "wait_check_confirm")
async def confirm_waiting_check(callback: CallbackQuery, state: FSMContext):
    """Подтверждение ожидания чека - переход к отправке чека"""
    user_id = callback.from_user.id

    # Получаем данные заказа из state
    data = await state.get_data()
    order_id = data.get('pending_order_id')

    if not order_id:
        await callback.answer("Ошибка: заказ не найден", show_alert=True)
        return

    text = (
        "💳 <b>Подтверждение оплаты</b>\n\n"
        f"Заказ #{order_id} ожидает подтверждения оплаты.\n\n"
        "📸 <b>Пожалуйста, отправьте фото чека или скриншот оплаты:</b>\n\n"
        "• Нажмите на скрепку 📎\n"
        "• Выберите фото или скриншот\n"
        "• Отправьте для подтверждения\n\n"
        "После проверки администратором заказ будет подтверждён."
    )

    builder = get_back_keyboard("cart")

    await safe_edit_text(
        callback,
        text,
        reply_markup=builder,
        parse_mode=ParseMode.HTML
    )
    await state.set_state(UserStates.waiting_payment_check)
    await callback.answer()


@payment_check_router.message(UserStates.waiting_payment_check, F.photo)
async def receive_payment_check(message: Message, state: FSMContext, bot: Bot):
    """Получение фото чека"""
    user_id = message.from_user.id
    data = await state.get_data()
    order_id = data.get('pending_order_id')

    if not order_id:
        await message.answer(
            "❌ Ошибка: заказ не найден. Попробуйте оформить заказ заново.",
            reply_markup=get_back_keyboard("main")
        )
        await state.clear()
        return

    # Получаем самое большое фото (лучшее качество)
    photo: PhotoSize = message.photo[-1]
    file_id = photo.file_id

    # Генерируем уникальное имя файла
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"check_{user_id}_{order_id}_{timestamp}.jpg"
    file_path = CHECKS_DIR / filename

    try:
        # Скачиваем файл
        file = await bot.download(file_id, destination=file_path)
        file_path_str = str(file_path.absolute())

        # Сохраняем путь к чеку в заказ
        async with get_db() as db:
            await db.execute(
                "UPDATE orders SET payment_check_path = ?, status = 'payment_pending' WHERE id = ? AND user_id = ?",
                (file_path_str, order_id, user_id)
            )

        await state.clear()

        text = (
            "✅ <b>Чек получен!</b>\n\n"
            "Спасибо за подтверждение оплаты.\n\n"
            "👨‍💼 <b>Администратор проверит чек и подтвердит заказ в ближайшее время.</b>\n\n"
            "Вы получите уведомление после проверки."
        )

        builder = get_back_keyboard("main")

        await message.answer(
            text,
            reply_markup=builder,
            parse_mode=ParseMode.HTML
        )

        # Отправляем уведомление администраторам
        await _notify_admins_about_payment(order_id, user_id)

        logger.info(f"✅ Чек для заказа #{order_id} получен от пользователя {user_id}")

    except Exception as e:
        logger.error(f"Ошибка сохранения чека: {e}", exc_info=True)
        await message.answer(
            "❌ Ошибка при загрузке чека. Попробуйте ещё раз или свяжитесь с поддержкой.",
            reply_markup=get_back_keyboard("cart")
        )


@payment_check_router.message(UserStates.waiting_payment_check)
async def reject_non_photo(message: Message):
    """Отклонение сообщений без фото"""
    await message.answer(
        "❌ Пожалуйста, отправьте именно <b>фото чека</b> (или скриншот).\n\n"
        "Нажмите на скрепку 📎 и выберите фото из галереи.",
        parse_mode=ParseMode.HTML
    )


async def _notify_admins_about_payment(order_id: int, user_id: int):
    """Уведомление администраторов о новом чеке"""
    from app.config import ADMIN_IDS

    global bot
    if not bot:
        logger.warning("Bot не инициализирован для отправки уведомлений")
        return

    try:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT total_price, items, u.first_name, u.username "
                "FROM orders o "
                "LEFT JOIN users u ON o.user_id = u.user_id "
                "WHERE o.id = ?",
                (order_id,)
            )
            order = await cursor.fetchone()

            if not order:
                return

            total_price, items, first_name, username = order
            user_info = f"@{username}" if username else f"{first_name} ({user_id})"

            text = (
                "💳 <b>Новый чек оплаты!</b>\n\n"
                f"Заказ #{order_id}\n"
                f"Пользователь: {user_info}\n"
                f"Сумма: {format_price(total_price)}\n\n"
                "📸 Чек загружен, требуется проверка.\n\n"
                "Нажмите кнопку ниже, чтобы проверить чеки:"
            )

            from aiogram.utils.keyboard import InlineKeyboardBuilder
            
            builder = InlineKeyboardBuilder()
            builder.button(text="📋 Проверить чеки", callback_data="admin_payment_checks")
            builder.adjust(1)
            
            # Отправляем уведомление админам
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=text,
                        reply_markup=builder.as_markup(),
                        parse_mode=ParseMode.HTML
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

        logger.info(f"✅ Админы уведомлены о новом чеке для заказа #{order_id}")

    except Exception as e:
        logger.error(f"Ошибка уведомления админов о чеке: {e}", exc_info=True)
