"""Утилиты для форматирования времени (Тайланд, UTC+7) и валюты"""
from datetime import datetime, timezone, timedelta
from typing import Optional
from app.config import TIMEZONE_OFFSET, CURRENCY_SYMBOL


def get_thailand_time() -> datetime:
    """Получить текущее время в Таиланде (UTC+7)"""
    utc_now = datetime.now(timezone.utc)
    thailand_tz = timezone(timedelta(hours=TIMEZONE_OFFSET))
    return utc_now.astimezone(thailand_tz)


def format_thailand_time(dt: Optional[datetime] = None, format_str: str = "%d.%m %H:%M") -> str:
    """
    Отформатировать время в тайском часовом поясе
    
    Args:
        dt: datetime объект (если None, используется текущее время Thailand)
        format_str: формат строки (по умолчанию: DD.MM HH:MM)
    
    Returns:
        Отформатированная строка времени
    """
    if dt is None:
        dt = get_thailand_time()
    elif dt.tzinfo is None:
        # Если время без часового пояса, предполагаем UTC
        dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone(timedelta(hours=TIMEZONE_OFFSET)))
    else:
        dt = dt.astimezone(timezone(timedelta(hours=TIMEZONE_OFFSET)))
    
    return dt.strftime(format_str)


def format_thailand_date(dt: Optional[datetime] = None, format_str: str = "%d.%m.%Y") -> str:
    """
    Отформатировать дату в тайском часовом поясе
    
    Args:
        dt: datetime объект (если None, используется текущая дата Thailand)
        format_str: формат строки (по умолчанию: DD.MM.YYYY)
    
    Returns:
        Отформатированная строка даты
    """
    if dt is None:
        dt = get_thailand_time()
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone(timedelta(hours=TIMEZONE_OFFSET)))
    else:
        dt = dt.astimezone(timezone(timedelta(hours=TIMEZONE_OFFSET)))
    
    return dt.strftime(format_str)


def format_price(amount: int, symbol: str = CURRENCY_SYMBOL) -> str:
    """
    Отформатировать цену с символом валюты
    
    Args:
        amount: сумма в целых числах
        symbol: символ валюты (по умолчанию: ฿)
    
    Returns:
        Отформатированная строка цены
    
    Examples:
        >>> format_price(1500)
        '1500฿'
        >>> format_price(1500, "₽")
        '1500₽'
    """
    return f"{amount}{symbol}"


def format_price_with_space(amount: int, symbol: str = CURRENCY_SYMBOL) -> str:
    """
    Отформатировать цену с пробелом перед символом валюты
    
    Args:
        amount: сумма в целых числах
        symbol: символ валюты (по умолчанию: ฿)
    
    Returns:
        Отформатированная строка цены
    
    Examples:
        >>> format_price_with_space(1500)
        '1500 ฿'
    """
    return f"{amount} {symbol}"
