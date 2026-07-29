"""Валидация пользовательского ввода"""
import re
from datetime import datetime
from typing import Optional


def validate_phone(phone: str) -> bool:
    """Валидация номера телефона"""
    pattern = r'^\+?7?\d{10,11}$'
    return bool(re.match(pattern, phone.replace(' ', '').replace('-', '')))


def validate_email(email: str) -> bool:
    """Валидация email"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_birth_date(date_str: str) -> bool:
    """Валидация даты рождения в формате ДД.ММ.ГГГГ"""
    try:
        datetime.strptime(date_str, "%d.%m.%Y")
        return True
    except ValueError:
        return False


def validate_address(address: str) -> bool:
    """Базовая валидация адреса"""
    return len(address.strip()) >= 5


def validate_time_format(time_str: str) -> Optional[datetime]:
    """Валидация времени в формате ДД.ММ ЧЧ:ММ"""
    try:
        parsed = datetime.strptime(f"{time_str.strip()} 2000", "%d.%m %H:%M %Y")
        now = datetime.now()

        for year in (now.year, now.year + 1):
            try:
                candidate = parsed.replace(year=year)
            except ValueError:
                continue

            if candidate >= now:
                return candidate

        return None
    except ValueError:
        return None


def validate_promo_code(code: str) -> bool:
    """Валидация промокода — только буквы и цифры"""
    return bool(re.match(r'^[A-Z0-9]{3,20}$', code.upper()))


def format_phone(phone: str) -> str:
    """Форматирование номера телефона"""
    cleaned = re.sub(r'[^\d+]', '', phone)
    if cleaned.startswith('8') and len(cleaned) == 11:
        cleaned = '+7' + cleaned[1:]
    elif cleaned.startswith('7') and len(cleaned) == 11:
        cleaned = '+' + cleaned
    return cleaned
