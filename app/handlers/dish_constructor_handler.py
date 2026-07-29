"""Обработчик конструктора блюд"""
import logging

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.enums import ParseMode

from app.config import ADMIN_IDS, CURRENCY_SYMBOL
from app.database import get_db
from app.states import UserStates
from app.services.dish_constructor import DishConstructorService
from app.models import IngredientItem, CustomDishItem
from app.keyboards.main import (
    get_main_menu_keyboard, get_dish_constructor_keyboard,
    get_template_keyboard, get_ingredients_keyboard,
    get_single_ingredient_keyboard, get_constructor_review_keyboard,
    get_back_keyboard,
)
from app.utils.thai_time import format_price

logger = logging.getLogger(__name__)
constructor_router = Router()


def _to_ingredient(d: dict) -> IngredientItem:
    return IngredientItem(
        id=d["id"], name=d["name"], price=d["price"],
        category_id=d["category_id"], category_type=d.get("category_type", ""),
        allergens=d.get("allergens", ""), diet_tags=d.get("diet_tags", ""),
        calories=d.get("calories", 0)
    )


# ==================== ГЛАВНОЕ МЕНЮ КОНСТРУКТОРА ====================

@constructor_router.callback_query(F.data == "constructor")
async def constructor_menu(callback: CallbackQuery):
    """Меню конструктора блюд"""
    await callback.message.edit_text(
        "🛠️ <b>Конструктор блюд</b>\n\n"
        "Создайте уникальное блюдо из свежих ингредиентов!\n"
        "Выберите шаблон, добавьте начинки и соусы — "
        "и получите блюдо по вашему вкусу.",
        reply_markup=get_dish_constructor_keyboard(),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


# ==================== ШАГ 1: ВЫБОР ШАБЛОНА ====================

@constructor_router.callback_query(F.data == "constructor_start")
async def start_constructor(callback: CallbackQuery, state: FSMContext):
    """Начать конструктор — выбор шаблона"""
    async with get_db() as db:
        service = DishConstructorService(db)
        templates = await service.get_dish_templates()

    if not templates:
        await callback.message.edit_text("😔 Конструктор временно недоступен.")
        await callback.answer()
        return

    text = "🍽️ <b>Выберите тип блюда</b>\n\n"
    for t in templates:
        text += f"{t['emoji']} <b>{t['name']}</b> — от {format_price(t['base_price'])}\n"
        text += f"  <i>{t['description']}</i>\n\n"

    await callback.message.edit_text(
        text,
        reply_markup=get_template_keyboard(templates),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@constructor_router.callback_query(F.data.startswith("tmpl_"))
async def select_template(callback: CallbackQuery, state: FSMContext):
    """Выбран шаблон — переходим к ингредиентам"""
    try:
        template_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return

    async with get_db() as db:
        service = DishConstructorService(db)
        templates = await service.get_dish_templates()

    template = next((t for t in templates if t["id"] == template_id), None)
    if not template:
        await callback.answer("Шаблон не найден", show_alert=True)
        return

    await state.update_data(constructor_template=template)
    await state.update_data(constructor_ingredients=[])
    await state.update_data(constructor_sauces=[])

    # Получаем категории для этого шаблона
    categories = await service.get_template_categories(template_id)

    # Определяем первую категорию (основа/белок)
    base_categories = [c for c in categories if c["category_type"] == "base"]
    side_categories = [c for c in categories if c["category_type"] == "side"]

    # Если есть категория "base" — начинаем с неё
    if base_categories:
        cat = base_categories[0]
        ingredients = await service.get_ingredients_by_category(cat["id"])
        await state.update_data(constructor_categories=categories)
        await state.update_data(constructor_current_cat=cat)
        await state.update_data(constructor_cat_index=0)
        await state.update_data(constructor_selected_base=None)  # одиночный выбор
        await state.set_state(UserStates.dish_constructor_base)

        await callback.message.edit_text(
            f"🥩 <b>Выберите основу</b>\n\n"
            f"{cat['label'] or cat['name']} — выберите один вариант:",
            reply_markup=get_single_ingredient_keyboard(ingredients),
            parse_mode=ParseMode.HTML
        )
    elif side_categories:
        cat = side_categories[0]
        ingredients = await service.get_ingredients_by_category(cat["id"])
        await state.update_data(constructor_categories=categories)
        await state.update_data(constructor_current_cat=cat)
        await state.update_data(constructor_cat_index=0)
        await state.update_data(constructor_selected_side=None)
        await state.set_state(UserStates.dish_constructor_side)

        await callback.message.edit_text(
            f"🍚 <b>Выберите гарнир</b>\n\n"
            f"{cat['label'] or cat['name']}:",
            reply_markup=get_single_ingredient_keyboard(ingredients),
            parse_mode=ParseMode.HTML
        )
    else:
        # Без категорий — сразу к топпингам
        await state.update_data(constructor_categories=categories)
        await state.update_data(constructor_cat_index=0)
        await _show_toppings(callback, state, service, template, categories, 0)
        return

    await callback.answer()


# ==================== ВЫБОР ОДНОГО ИНГРЕДИЕНТА (основа/гарнир) ====================

@constructor_router.callback_query(F.data.startswith("ing_"), UserStates.dish_constructor_base)
@constructor_router.callback_query(F.data.startswith("ing_"), UserStates.dish_constructor_side)
async def select_single_ingredient(callback: CallbackQuery, state: FSMContext):
    """Выбор одного ингредиента (основа/гарнир)"""
    # Обработка кнопок навигации
    if callback.data == "ing_skip":
        await skip_category(callback, state)
        return

    if callback.data == "ing_done":
        await ingredient_done(callback, state)
        return

    # Извлекаем ID ингредиента (формат: ing_<id>)
    parts = callback.data.split("_", 1)
    if len(parts) < 2:
        await callback.answer("Ошибка: некорректные данные", show_alert=True)
        return

    try:
        ing_id = int(parts[1])
    except ValueError:
        await callback.answer("Ошибка: некорректный ID ингредиента", show_alert=True)
        return

    async with get_db() as db:
        service = DishConstructorService(db)
        data = await state.get_data()
        cat = data.get("constructor_current_cat", {})

    ingredient = await service.get_ingredient_by_id(ing_id)
    if not ingredient:
        await callback.answer("Ингредиент не найден", show_alert=True)
        return

    # Обновляем выбранный в зависимости от текущего состояния
    current_state = await state.get_state()
    if current_state == UserStates.dish_constructor_base.state:
        await state.update_data(constructor_selected_base=ingredient)
    elif current_state == UserStates.dish_constructor_side.state:
        await state.update_data(constructor_selected_side=ingredient)

    # Обновляем клавиатуру с отметкой
    ingredients = await service.get_ingredients_by_category(cat["id"])
    kb = get_single_ingredient_keyboard(ingredients, selected_id=ing_id)

    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer(f"✅ {ingredient['name']}")


@constructor_router.callback_query(F.data == "ing_done")
async def ingredient_done(callback: CallbackQuery, state: FSMContext):
    """Готово с ингредиентами — переходим к следующей категории или итогу"""
    current_state = await state.get_state()

    data = await state.get_data()
    template = data.get("constructor_template")
    categories = data.get("constructor_categories", [])
    cat_index = data.get("constructor_cat_index", 0)

    async with get_db() as db:
        service = DishConstructorService(db)

    # Если мы в состояниях топпингов/соусов — это «Далее» в множественном выборе
    if current_state in (UserStates.dish_constructor_topping.state,
                          UserStates.dish_constructor_sauce.state):
        next_index = cat_index + 1
        if next_index < len(categories):
            next_cat = categories[next_index]
            await state.update_data(constructor_cat_index=next_index)
            await state.update_data(constructor_current_cat=next_cat)

            if next_cat["category_type"] == "topping":
                await state.update_data(constructor_selected_toppings=
                    data.get("constructor_selected_toppings", []))
                await _show_toppings(callback, state, service, template, categories, next_index)
            elif next_cat["category_type"] == "sauce":
                await state.update_data(constructor_selected_sauces=
                    data.get("constructor_selected_sauces", []))
                await _show_sauces(callback, state, service, template, categories, next_index)
            else:
                await ingredient_done(callback, state)
        else:
            await _show_review(callback, state, service)
        await callback.answer()
        return

    # Иначе — это «Далее» после одиночного выбора (основа/гарнир)
    next_index = cat_index + 1
    if next_index < len(categories):
        next_cat = categories[next_index]
        await state.update_data(constructor_cat_index=next_index)
        await state.update_data(constructor_current_cat=next_cat)

        ingredients = await service.get_ingredients_by_category(next_cat["id"])

        if next_cat["category_type"] == "side":
            await state.set_state(UserStates.dish_constructor_side)
            await state.update_data(constructor_selected_side=None)
            await callback.message.edit_text(
                f"🍚 <b>Выберите гарнир</b>\n\n{next_cat.get('label', next_cat['name'])}:",
                reply_markup=get_single_ingredient_keyboard(ingredients),
                parse_mode=ParseMode.HTML
            )
        elif next_cat["category_type"] == "topping":
            await state.update_data(constructor_selected_toppings=[])
            await _show_toppings(callback, state, service, template, categories, next_index)
        elif next_cat["category_type"] == "sauce":
            await state.update_data(constructor_selected_sauces=[])
            await _show_sauces(callback, state, service, template, categories, next_index)
        else:
            # Пропускаем неизвестную категорию
            await ingredient_done(callback, state)
    else:
        # Все категории пройдены — показываем итог
        await _show_review(callback, state, service)

    await callback.answer()


@constructor_router.callback_query(F.data == "ing_skip")
async def skip_category(callback: CallbackQuery, state: FSMContext):
    """Пропустить текущую категорию"""
    data = await state.get_data()
    template = data.get("constructor_template")
    categories = data.get("constructor_categories", [])
    cat_index = data.get("constructor_cat_index", 0)

    next_index = cat_index + 1
    if next_index < len(categories):
        await state.update_data(constructor_cat_index=next_index)
        await state.update_data(constructor_current_cat=categories[next_index])
        await ingredient_done(callback, state)
    else:
        async with get_db() as db:
            service = DishConstructorService(db)
            await _show_review(callback, state, service)
        await callback.answer()

    await callback.answer()


# ==================== ВЫБОР ТОПИНГОВ (множественный) ====================

async def _show_toppings(callback, state, service, template, categories, cat_index):
    """Показать выбор топпингов"""
    cat = categories[cat_index]
    ingredients = await service.get_ingredients_by_category(cat["id"])
    data = await state.get_data()
    selected = set(data.get("constructor_selected_toppings", []))

    await state.set_state(UserStates.dish_constructor_topping)

    max_t = template.get("max_toppings", 5)
    await callback.message.edit_text(
        f"🥬 <b>Добавки и топпинги</b>\n\n"
        f"{cat.get('label', cat['name'])}\n"
        f"Максимум: {max_t} шт.",
        reply_markup=get_ingredients_keyboard(ingredients, selected, max_select=max_t),
        parse_mode=ParseMode.HTML
    )


@constructor_router.callback_query(F.data.startswith("ing_"), UserStates.dish_constructor_topping)
async def toggle_topping(callback: CallbackQuery, state: FSMContext):
    """Переключение топпинга"""
    try:
        ing_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return

    data = await state.get_data()
    selected = set(data.get("constructor_selected_toppings", []))
    template = data.get("constructor_template", {})
    categories = data.get("constructor_categories", [])
    cat_index = data.get("constructor_cat_index", 0)

    if ing_id in selected:
        selected.remove(ing_id)
    else:
        max_t = template.get("max_toppings", 5)
        if len(selected) >= max_t:
            await callback.answer(f"Максимум {max_t} добавок", show_alert=True)
            return
        selected.add(ing_id)

    await state.update_data(constructor_selected_toppings=list(selected))

    async with get_db() as db:
        service = DishConstructorService(db)
        cat = categories[cat_index]
        ingredients = await service.get_ingredients_by_category(cat["id"])

    kb = get_ingredients_keyboard(ingredients, selected, max_select=template.get("max_toppings", 5))
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


# ==================== ВЫБОР СОУСОВ (множественный) ====================

async def _show_sauces(callback, state, service, template, categories, cat_index):
    """Показать выбор соусов"""
    cat = categories[cat_index]
    ingredients = await service.get_ingredients_by_category(cat["id"])
    data = await state.get_data()
    selected = set(data.get("constructor_selected_sauces", []))

    await state.set_state(UserStates.dish_constructor_sauce)

    max_s = template.get("max_sauces", 2)
    await callback.message.edit_text(
        f"🫗 <b>Соусы</b>\n\n"
        f"{cat.get('label', cat['name'])}\n"
        f"Максимум: {max_s} шт.",
        reply_markup=get_ingredients_keyboard(ingredients, selected, max_select=max_s),
        parse_mode=ParseMode.HTML
    )


@constructor_router.callback_query(F.data.startswith("ing_"), UserStates.dish_constructor_sauce)
async def toggle_sauce(callback: CallbackQuery, state: FSMContext):
    """Переключение соуса"""
    try:
        ing_id = int(callback.data.rsplit("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("[ERR] Ошибка данных", show_alert=True)
        return

    data = await state.get_data()
    selected = set(data.get("constructor_selected_sauces", []))
    template = data.get("constructor_template", {})

    if ing_id in selected:
        selected.remove(ing_id)
    else:
        max_s = template.get("max_sauces", 2)
        if len(selected) >= max_s:
            await callback.answer(f"Максимум {max_s} соусов", show_alert=True)
            return
        selected.add(ing_id)

    await state.update_data(constructor_selected_sauces=list(selected))

    async with get_db() as db:
        service = DishConstructorService(db)
        categories = data.get("constructor_categories", [])
        cat_index = data.get("constructor_cat_index", 0)
        cat = categories[cat_index]
        ingredients = await service.get_ingredients_by_category(cat["id"])

    kb = get_ingredients_keyboard(ingredients, selected, max_select=template.get("max_sauces", 2))
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()


# ==================== ИТОГ / REVIEW ====================


async def _show_review(callback, state, service: DishConstructorService):
    """Показать итог конструктора"""
    data = await state.get_data()
    template = data.get("constructor_template")

    if not template:
        await callback.message.edit_text("❌ Ошибка: шаблон не выбран.")
        return

    # Собираем ингредиенты
    base_ing = data.get("constructor_selected_base")
    side_ing = data.get("constructor_selected_side")

    topping_ids = data.get("constructor_selected_toppings", [])
    sauce_ids = data.get("constructor_selected_sauces", [])

    ingredients_list = []
    sauces_list = []

    if base_ing:
        ingredients_list.append(base_ing)
    if side_ing:
        ingredients_list.append(side_ing)

    async def _get_ing(ing_id):
        return await service.get_ingredient_by_id(ing_id)

    for tid in topping_ids:
        ing = await _get_ing(tid)
        if ing:
            ingredients_list.append(ing)

    for sid in sauce_ids:
        ing = await _get_ing(sid)
        if ing:
            sauces_list.append(ing)

    # Считаем цену
    total_price = service.calculate_price(template, ingredients_list, sauces_list)
    dish_name = service.generate_dish_name(template, ingredients_list, sauces_list)

    # Формируем описание
    emoji = template.get("emoji", "🍽️")
    text = f"{emoji} <b>Ваше блюдо готово!</b>\n\n"
    text += f"📛 <b>{dish_name}</b>\n\n"

    if ingredients_list:
        text += "🥘 <b>Состав:</b>\n"
        for ing in ingredients_list:
            text += f"• {ing['name']} — {format_price(ing['price'])}\n"
        text += "\n"

    if sauces_list:
        text += "🫗 <b>Соусы:</b>\n"
        for s in sauces_list:
            text += f"• {s['name']} — {format_price(s['price'])}\n"
        text += "\n"

    # Аллергены
    allergens = service.format_allergens(ingredients_list, sauces_list)
    if allergens:
        text += f"{allergens}\n\n"

    text += f"💰 <b>Итого: {format_price(total_price)}</b>"

    # Сохраняем для последующего использования
    await state.update_data(constructor_total_price=total_price)
    await state.update_data(constructor_dish_name=dish_name)
    await state.update_data(constructor_final_ingredients_ids=[i["id"] for i in ingredients_list])
    await state.update_data(constructor_final_sauce_ids=[s["id"] for s in sauces_list])
    await state.set_state(UserStates.dish_constructor_review)

    await callback.message.edit_text(
        text,
        reply_markup=get_constructor_review_keyboard(),
        parse_mode=ParseMode.HTML
    )


# ==================== ДОБАВИТЬ В КОРЗИНУ ====================

@constructor_router.callback_query(F.data == "constructor_to_cart")
async def add_to_cart(callback: CallbackQuery, state: FSMContext):
    """Добавить кастомное блюдо в корзину"""
    data = await state.get_data()
    user_id = callback.from_user.id

    template = data.get("constructor_template")
    if not template:
        await callback.answer("Ошибка: нет шаблона", show_alert=True)
        return

    # Получаем полные данные ингредиентов
    async with get_db() as db:
        service = DishConstructorService(db)

        ing_ids = data.get("constructor_final_ingredients_ids", [])
        sauce_ids = data.get("constructor_final_sauce_ids", [])

        ingredients = []
        for iid in ing_ids:
            ing = await service.get_ingredient_by_id(iid)
            if ing:
                ingredients.append(ing)

        sauces = []
        for sid in sauce_ids:
            ing = await service.get_ingredient_by_id(sid)
            if ing:
                sauces.append(ing)

        total_price = service.calculate_price(template, ingredients, sauces)
        dish_name = service.generate_dish_name(template, ingredients, sauces)

        # Создаём CustomDishItem
        custom_dish = CustomDishItem(
            template_name=template["name"],
            template_emoji=template.get("emoji", "🍽️"),
            ingredients=[_to_ingredient(i) for i in ingredients],
            sauces=[_to_ingredient(s) for s in sauces],
            base_price=total_price,
            total_price=total_price,
            dish_name=dish_name,
        )

        # Добавляем в корзину
        cart_id = await service.add_custom_dish_to_cart(user_id, custom_dish)

    if not cart_id:
        await callback.message.edit_text("❌ Ошибка при добавлении в корзину.")
        return

    await callback.message.edit_text(
        f"✅ <b>Добавлено в корзину!</b>\n\n"
        f"{dish_name}\n"
        f"💰 {format_price(total_price)}",
        reply_markup=get_main_menu_keyboard(
            is_admin=(user_id in __import__('app.config', fromlist=['ADMIN_IDS']).ADMIN_IDS),
            has_cart=True
        ),
        parse_mode=ParseMode.HTML
    )

    await state.clear()
    await callback.answer()


# ==================== НАВИГАЦИЯ ====================

@constructor_router.callback_query(F.data == "constructor_edit")
async def edit_dish(callback: CallbackQuery, state: FSMContext):
    """Редактировать — вернуться к выбору шаблона"""
    await start_constructor(callback, state)


@constructor_router.callback_query(F.data == "constructor_cancel")
async def cancel_constructor(callback: CallbackQuery, state: FSMContext):
    """Отменить конструктор"""
    await state.clear()
    user_id = callback.from_user.id
    await callback.message.edit_text(
        "🛠️ Конструктор отменён.",
        reply_markup=get_main_menu_keyboard(
            is_admin=(user_id in __import__('app.config', fromlist=['ADMIN_IDS']).ADMIN_IDS)
        ),
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@constructor_router.callback_query(F.data == "constructor_back")
async def back_in_constructor(callback: CallbackQuery, state: FSMContext):
    """Назад в конструкторе — вернуться к выбору шаблона"""
    await start_constructor(callback, state)
