"""Утилиты для безопасной работы с сообщениями"""
import logging
from typing import Optional, Union
from aiogram.types import CallbackQuery, Message
from aiogram.types import InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButtonPollType
from aiogram.enums import ParseMode

logger = logging.getLogger(__name__)


async def safe_edit_text(
    event: Union[CallbackQuery, Message],
    text: str,
    reply_markup: Optional[Union[InlineKeyboardMarkup, ReplyKeyboardMarkup]] = None,
    parse_mode: Optional[ParseMode] = ParseMode.HTML,
    **kwargs
) -> bool:
    """
    Безопасное редактирование текста сообщения.
    
    Обрабатывает типичные ошибки:
    - Message not modified (когда контент не изменился)
    - Message can't be edited (старое сообщение или бот не админ)
    - Message is too long
    
    Args:
        event: CallbackQuery или Message
        text: Текст сообщения
        reply_markup: Клавиатура (опционально)
        parse_mode: Режим парсинга (по умолчанию HTML)
        **kwargs: Дополнительные аргументы для edit_text
    
    Returns:
        bool: True если успешно, False если ошибка
    """
    try:
        if isinstance(event, CallbackQuery):
            await event.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                **kwargs
            )
        elif isinstance(event, Message):
            await event.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                **kwargs
            )
        return True
        
    except Exception as e:
        error_msg = str(e)
        
        # Игнорируем типичные ошибки редактирования
        if "message is not modified" in error_msg.lower():
            # Контент не изменился — это нормально
            return True
        elif "message can't be edited" in error_msg.lower():
            # Сообщение слишком старое или бот не может редактировать
            logger.debug(f"Сообщение нельзя отредактировать: {error_msg}")
            # Отправляем новое сообщение вместо редактирования
            try:
                if isinstance(event, CallbackQuery):
                    await event.message.answer(
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                        **kwargs
                    )
                elif isinstance(event, Message):
                    await event.answer(
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                        **kwargs
                    )
                return True
            except Exception as fallback_error:
                logger.error(f"Ошибка отправки сообщения: {fallback_error}")
                return False
        elif "message is too long" in error_msg.lower():
            logger.error(f"Текст слишком длинный: {len(text)} символов")
            # Обрезаем до безопасной длины
            try:
                truncated_text = text[:4000] + "\n\n... (продолжение)"
                if isinstance(event, CallbackQuery):
                    await event.message.edit_text(
                        text=truncated_text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                        **kwargs
                    )
                elif isinstance(event, Message):
                    await event.edit_text(
                        text=truncated_text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                        **kwargs
                    )
                return True
            except Exception as fallback_error:
                logger.error(f"Ошибка отправки сокращённого сообщения: {fallback_error}")
                return False
        else:
            # Другие ошибки логируем
            logger.warning(f"Ошибка редактирования сообщения: {error_msg}")
            return False


async def safe_answer_callback(
    callback: CallbackQuery,
    text: str = "",
    show_alert: bool = False,
    **kwargs
) -> bool:
    """
    Безопасный ответ на callback query.
    
    Args:
        callback: CallbackQuery объект
        text: Текст уведомления
        show_alert: Показать как alert (модальное окно)
        **kwargs: Дополнительные аргументы
    
    Returns:
        bool: True если успешно
    """
    try:
        await callback.answer(text=text, show_alert=show_alert, **kwargs)
        return True
    except Exception as e:
        logger.warning(f"Ошибка answer callback: {e}")
        return False
