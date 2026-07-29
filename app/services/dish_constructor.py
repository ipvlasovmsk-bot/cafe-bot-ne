"""Сервис конструктора блюд"""
import logging
import json
from typing import Optional
from datetime import datetime

import aiosqlite

from app.models import IngredientItem, CustomDishItem
from app.utils.thai_time import format_price

logger = logging.getLogger(__name__)


class DishConstructorService:
    """Управление конструктором блюд"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_dish_templates(self) -> list[dict]:
        """Получить все активные шаблоны блюд"""
        cursor = await self.db.execute(
            "SELECT id, name, description, base_price, emoji, max_toppings, max_sauces "
            "FROM dish_templates WHERE is_active = 1 ORDER BY id"
        )
        columns = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def get_template_categories(self, template_id: int) -> list[dict]:
        """Получить категории для шаблона с информацией о типах"""
        cursor = await self.db.execute(
            """SELECT ic.id, ic.name, ic.category_type, dtc.is_required,
                      dtc.min_select, dtc.max_select, dtc.label
               FROM dish_template_categories dtc
               JOIN ingredient_categories ic ON dtc.category_id = ic.id
               WHERE dtc.template_id = ?
               ORDER BY ic.sort_order""",
            (template_id,)
        )
        columns = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def get_ingredients_by_category(self, category_id: int) -> list[dict]:
        """Получить ингредиенты по категории"""
        cursor = await self.db.execute(
            """SELECT i.id, i.name, i.price, i.category_id, ic.category_type,
                      i.allergens, i.diet_tags, i.calories
               FROM ingredients i
               JOIN ingredient_categories ic ON i.category_id = ic.id
               WHERE i.category_id = ? AND i.is_active = 1
               ORDER BY i.sort_order, i.name""",
            (category_id,)
        )
        columns = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def get_categories_by_type(self, category_type: str) -> list[dict]:
        """Получить категории по типу (base, side, topping, sauce)"""
        cursor = await self.db.execute(
            """SELECT id, name, category_type
               FROM ingredient_categories
               WHERE category_type = ?
               ORDER BY sort_order""",
            (category_type,)
        )
        columns = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def get_all_ingredients(self) -> list[dict]:
        """Получить все активные ингредиенты"""
        cursor = await self.db.execute(
            """SELECT i.id, i.name, i.price, i.category_id, ic.category_type,
                      i.allergens, i.diet_tags, i.calories
               FROM ingredients i
               JOIN ingredient_categories ic ON i.category_id = ic.id
               WHERE i.is_active = 1
               ORDER BY ic.sort_order, i.sort_order"""
        )
        columns = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def get_ingredient_by_id(self, ingredient_id: int) -> Optional[dict]:
        """Получить ингредиент по ID"""
        cursor = await self.db.execute(
            """SELECT i.id, i.name, i.price, i.category_id, ic.category_type,
                      i.allergens, i.diet_tags, i.calories
               FROM ingredients i
               JOIN ingredient_categories ic ON i.category_id = ic.id
               WHERE i.id = ?""",
            (ingredient_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    def calculate_price(self, template: dict, ingredients: list[dict],
                        sauces: list[dict]) -> int:
        """Рассчитать итоговую цену"""
        total = template.get("base_price", 0)
        for ing in ingredients:
            total += ing.get("price", 0)
        for sauce in sauces:
            total += sauce.get("price", 0)
        return total

    def generate_dish_name(self, template: dict, ingredients: list[dict],
                            sauces: list[dict]) -> str:
        """Сгенерировать название блюда"""
        emoji = template.get("emoji", "🍽️")
        template_name = template.get("name", "Блюдо")

        parts = []
        # Главный ингредиент (первый)
        if ingredients:
            parts.append(ingredients[0].get("name", ""))

        # Добавки (до 3)
        if len(ingredients) > 1:
            extras = [i.get("name", "") for i in ingredients[1:4]]
            parts.extend(extras)

        name = ", ".join(parts) if parts else template_name
        return f"{emoji} {template_name} «{name}»"

    def format_ingredients_list(self, ingredients: list[dict],
                                 sauces: list[dict]) -> str:
        """Форматированный список ингредиентов для отображения"""
        lines = []
        for ing in ingredients:
            lines.append(f"• {ing['name']} (+{format_price(ing['price'])})")
        for sauce in sauces:
            lines.append(f"🫗 {sauce['name']} (+{format_price(sauce['price'])})")
        return "\n".join(lines) if lines else "—"

    def format_allergens(self, ingredients: list[dict],
                         sauces: list[dict]) -> str:
        """Собрать список аллергенов"""
        allergens = set()
        for item in ingredients + sauces:
            if item.get("allergens"):
                for a in item["allergens"].split(","):
                    a = a.strip()
                    if a:
                        allergens.add(a)
        if not allergens:
            return ""
        allergen_names = {
            "dairy": "молочные",
            "gluten": "глютен",
            "nuts": "орехи",
            "egg": "яйца",
            "fish": "рыба",
            "shellfish": "морепродукты",
            "soy": "соя",
        }
        return "⚠️ Аллергены: " + ", ".join(
            allergen_names.get(a, a) for a in sorted(allergens)
        )

    async def add_custom_dish_to_cart(self, user_id: int, custom_dish: CustomDishItem) -> int:
        """Добавить кастомное блюдо в корзину"""
        # Сериализуем состав
        ingredients_data = {
            "template": custom_dish.template_name,
            "ingredients": [{"id": i.id, "name": i.name, "price": i.price}
                            for i in custom_dish.ingredients],
            "sauces": [{"id": s.id, "name": s.name, "price": s.price}
                       for s in custom_dish.sauces],
        }

        now = datetime.now().isoformat()
        cursor = await self.db.execute(
            """INSERT INTO cart (user_id, dish_id, dish_name, ingredients,
                                 extra_price, base_price, added_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                -1,  # dish_id = -1 для кастомных блюд
                custom_dish.dish_name,
                json.dumps(ingredients_data, ensure_ascii=False),
                0,   # extra_price = 0, вся цена в base_price
                custom_dish.total_price,
                now,
            )
        )
        await self.db.commit()
        return cursor.lastrowid
