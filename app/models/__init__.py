"""Модели данных — Enums и Dataclass"""
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class OrderPriority(Enum):
    NORMAL = "normal"
    VIP = "vip"
    PREORDER = "preorder"


class OrderStatus(Enum):
    NEW = "new"
    ACCEPTED = "accepted"
    PREP = "prep"
    COOKING = "cooking"
    ASSEMBLY = "assembly"
    READY = "ready"
    DELIVERING = "delivering"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class LoyaltyLevel(Enum):
    NONE = "none"
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


class ReservationStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


class TableLocation(Enum):
    WINDOW = "window"
    HALL = "hall"
    CORNER = "corner"
    VIP = "vip"
    TERRACE = "terrace"


class DietType(Enum):
    NONE = "none"
    VEGAN = "vegan"
    VEGETARIAN = "vegetarian"
    GLUTEN_FREE = "gluten_free"
    DAIRY_FREE = "dairy_free"
    NUT_FREE = "nut_free"
    KETO = "keto"


class IngredientType(Enum):
    """Тип категории ингредиентов"""
    BASE = "base"       # Мясо/белок
    SIDE = "side"       # Гарнир
    TOPPING = "topping" # Овощи, сыры
    SAUCE = "sauce"     # Соусы


@dataclass
class KitchenTimer:
    order_id: int
    stage: str
    start_time: datetime
    estimated_end: datetime
    actual_end: Optional[datetime] = None


@dataclass
class DeliveryZone:
    name: str
    min_order: int
    delivery_cost: int
    free_from: int
    polygon: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class IngredientItem:
    """Один ингредиент в конструкторе блюд"""
    id: int
    name: str
    price: int
    category_id: int
    category_type: str = ""
    allergens: str = ""
    diet_tags: str = ""
    calories: int = 0


@dataclass
class CustomDishItem:
    """Кастомное блюдо, собранное в конструкторе"""
    template_name: str       # Салат, Паста, Вок...
    template_emoji: str      # Эмодзи шаблона
    ingredients: list[IngredientItem] = field(default_factory=list)
    sauces: list[IngredientItem] = field(default_factory=list)
    base_price: int = 0      # Базовая цена шаблона
    total_price: int = 0     # Итоговая цена
    dish_name: str = ""      # Сгенерированное название
