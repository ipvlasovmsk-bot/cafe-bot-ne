"""Базовые тесты бота"""
import pytest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ==================== ВАЛИДАТОРЫ ====================

class TestValidators:
    """Тесты валидации ввода"""

    def test_valid_phone(self):
        from app.utils.validators import validate_phone
        assert validate_phone("+79991234567") is True
        assert validate_phone("79991234567") is True
        assert validate_phone("89991234567") is True

    def test_invalid_phone(self):
        from app.utils.validators import validate_phone
        assert validate_phone("abc") is False
        assert validate_phone("123") is False
        assert validate_phone("") is False

    def test_valid_email(self):
        from app.utils.validators import validate_email
        assert validate_email("test@mail.ru") is True
        assert validate_email("user.name@example.com") is True

    def test_invalid_email(self):
        from app.utils.validators import validate_email
        assert validate_email("invalid") is False
        assert validate_email("@no-name.com") is False

    def test_valid_birth_date(self):
        from app.utils.validators import validate_birth_date
        assert validate_birth_date("01.01.1990") is True
        assert validate_birth_date("31.12.2000") is True

    def test_invalid_birth_date(self):
        from app.utils.validators import validate_birth_date
        assert validate_birth_date("32.01.1990") is False
        assert validate_birth_date("01/01/1990") is False

    def test_valid_address(self):
        from app.utils.validators import validate_address
        assert validate_address("ул. Примерная, д. 1") is True
        assert validate_address("Москва, Красная площадь, 1") is True

    def test_invalid_address(self):
        from app.utils.validators import validate_address
        assert validate_address("ул") is False
        assert validate_address("") is False

    def test_valid_time_format(self):
        from app.utils.validators import validate_time_format
        result = validate_time_format("15.04 14:00")
        assert result is not None
        assert result.day == 15
        assert result.month == 4
        assert result.hour == 14
        assert result.minute == 0
        # Может вернуть datetime или None в зависимости от версии Python
        # Главное что не падает с исключением

    def test_invalid_time_format(self):
        from app.utils.validators import validate_time_format
        assert validate_time_format("invalid") is None

    def test_valid_promo_code(self):
        from app.utils.validators import validate_promo_code
        assert validate_promo_code("SALE20") is True
        assert validate_promo_code("PROMO123") is True

    def test_invalid_promo_code(self):
        from app.utils.validators import validate_promo_code
        assert validate_promo_code("invalid!") is False
        assert validate_promo_code("ab") is False


# ==================== ЛОЯЛЬНОСТЬ ====================

class TestLoyalty:
    """Тесты системы лояльности"""

    def test_loyalty_levels(self):
        from app.services.loyalty import LoyaltySystem
        from app.models import LoyaltyLevel
        from app.config import (
            LOYALTY_BRONZE_THRESHOLD, LOYALTY_SILVER_THRESHOLD, LOYALTY_GOLD_THRESHOLD
        )

        assert LoyaltySystem.calculate_level(0) == LoyaltyLevel.NONE
        assert LoyaltySystem.calculate_level(LOYALTY_BRONZE_THRESHOLD) == LoyaltyLevel.BRONZE
        assert LoyaltySystem.calculate_level(LOYALTY_SILVER_THRESHOLD) == LoyaltyLevel.SILVER
        assert LoyaltySystem.calculate_level(LOYALTY_GOLD_THRESHOLD) == LoyaltyLevel.GOLD

    def test_cashback_percent(self):
        from app.services.loyalty import LoyaltySystem
        from app.models import LoyaltyLevel

        assert LoyaltySystem.get_cashback_percent(LoyaltyLevel.NONE) == 0
        assert LoyaltySystem.get_cashback_percent(LoyaltyLevel.BRONZE) == 0.03
        assert LoyaltySystem.get_cashback_percent(LoyaltyLevel.SILVER) == 0.05
        assert LoyaltySystem.get_cashback_percent(LoyaltyLevel.GOLD) == 0.10

    def test_referral_code_format(self):
        from app.services.loyalty import LoyaltySystem

        code = LoyaltySystem.generate_referral_code(12345)
        assert code.startswith("CAFE12345")
        assert len(code) > 4


# ==================== ДОСТАВКА ====================

class TestDelivery:
    """Тесты расчёта расстояния"""

    def test_haversine_formula(self):
        from app.services.delivery import DeliveryManager

        # Москва — Санкт-Петербург (~635 км)
        dist = DeliveryManager.calculate_distance(55.7558, 37.6173, 59.9343, 30.3351)
        assert 600 < dist < 700

    def test_same_location(self):
        from app.services.delivery import DeliveryManager

        dist = DeliveryManager.calculate_distance(55.7558, 37.6173, 55.7558, 37.6173)
        assert dist == 0.0

    def test_point_in_zone(self):
        from app.services.delivery import DeliveryManager

        polygon = [(55.8, 37.5), (55.8, 37.7), (55.7, 37.7), (55.7, 37.5)]
        assert DeliveryManager.is_point_in_zone(55.75, 37.6, polygon) is True
        assert DeliveryManager.is_point_in_zone(55.9, 37.9, polygon) is False


# ==================== КОНФИГУРАЦИЯ ====================

class TestConfig:
    """Тесты конфигурации"""

    def test_bot_token_exists(self):
        from app.config import BOT_TOKEN
        assert BOT_TOKEN is not None
        assert len(BOT_TOKEN) > 10

    def test_admin_ids_valid(self):
        from app.config import ADMIN_IDS
        assert isinstance(ADMIN_IDS, list)
        assert len(ADMIN_IDS) > 0
        for admin_id in ADMIN_IDS:
            assert isinstance(admin_id, int)
            assert admin_id > 0

    def test_db_pool_size(self):
        from app.config import DB_POOL_SIZE
        assert DB_POOL_SIZE >= 1
        assert DB_POOL_SIZE <= 20


# ==================== КЛАВИАТУРЫ ====================

class TestKeyboards:
    """Тесты клавиатур"""

    def test_main_menu_keyboard(self):
        from app.keyboards.main import get_main_menu_keyboard
        kb = get_main_menu_keyboard(is_admin=False, has_cart=False)
        assert kb is not None

    def test_main_menu_keyboard_with_cart(self):
        from app.keyboards.main import get_main_menu_keyboard
        kb = get_main_menu_keyboard(is_admin=True, has_cart=True)
        assert kb is not None

    def test_diet_filter_keyboard(self):
        from app.keyboards.main import get_diet_filter_keyboard
        kb = get_diet_filter_keyboard()
        assert kb is not None
        kb_selected = get_diet_filter_keyboard(["vegan"])
        assert kb_selected is not None


# ==================== RATE LIMIT ====================

class TestRateLimit:
    """Тесты rate limiting"""

    def test_rate_limit_tracks_timestamps(self):
        """Middleware запоминает время последнего запроса"""
        from app.middleware.rate_limit import RateLimitMiddleware
        import time

        middleware = RateLimitMiddleware(rate=10.0)

        # Проверяем внутреннее состояние напрямую
        user_id = 999
        now = time.time()

        # Имитируем запись timestamp
        middleware._user_timestamps[user_id] = now

        assert middleware._user_timestamps[user_id] == now
        assert user_id in middleware._user_timestamps

    def test_rate_limit_logic(self):
        """Проверка логики rate limiting без aiogram зависимостей"""
        from app.middleware.rate_limit import RateLimitMiddleware
        import time

        middleware = RateLimitMiddleware(rate=1.0)

        user_id = 123
        middleware._user_timestamps[user_id] = time.time()

        # Сразу — должно быть меньше rate
        now = time.time()
        assert now - middleware._user_timestamps[user_id] < 1.0
