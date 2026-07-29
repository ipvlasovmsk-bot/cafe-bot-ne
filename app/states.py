"""FSM состояния приложения"""
from aiogram.fsm.state import State, StatesGroup


class UserStates(StatesGroup):
    """Состояния для пользователей"""
    entering_address = State()
    selecting_delivery_time = State()
    entering_profile_data = State()
    entering_promo_code = State()
    waiting_payment_check = State()
    # Бронирование столика
    reservation_select_date = State()
    reservation_select_time = State()
    reservation_select_table = State()
    reservation_guest_info = State()
    reservation_requests = State()
    reservation_confirm = State()
    # Конструктор блюд
    dish_constructor_template = State()
    dish_constructor_base = State()
    dish_constructor_side = State()
    dish_constructor_topping = State()
    dish_constructor_sauce = State()
    dish_constructor_review = State()
    dish_constructor_cart = State()


class AdminStates(StatesGroup):
    """Состояния для администраторов"""
    adding_dish_photo = State()
    adding_dish = State()
    adding_courier = State()
    creating_promo = State()
    broadcasting = State()
    editing_dish = State()
    reservation_comment = State()
    courier_photo = State()
    reject_order = State()
