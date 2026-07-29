# 🔘 Аудит кнопок и навигации

## ✅ Все callback_data и их обработчики

### Главное меню
| Кнопка | callback_data | Обработчик | Статус |
|--------|--------------|------------|--------|
| 🍽️ Меню | `menu` | `show_menu()` | ✅ |
| 🛒 Корзина | `cart` | `show_cart_handler()` | ✅ |
| 🛠️ Конструктор | `constructor` | `constructor_menu()` | ✅ |
| ⭐ Избранное | `favorites` | `show_favorites()` | ✅ |
| 🤖 Рекомендации | `recommendations` | `show_recommendations()` | ✅ |
| 🍲 Блюдо дня | `dish_of_day` | `show_dish_of_day()` | ✅ |
| 📦 Мои заказы | `my_orders` | `show_my_orders()` | ✅ |
| 📅 Бронирование | `reservation` | `reservation_menu()` | ✅ |
| 💎 Баллы | `loyalty` | `show_loyalty()` | ✅ |
| 👤 Профиль | `profile` | `show_profile()` | ✅ |
| 📍 Адрес кафе | `cafe_info` | `show_cafe_info()` | ✅ |
| 🔧 Админ панель | `admin_panel` | `admin_panel()` | ✅ (admin only) |

### Навигация
| Кнопка | callback_data | Обработчик | Статус |
|--------|--------------|------------|--------|
| 🔙 Назад | `back_to_main` | `back_to_main()` | ✅ |
| 🔙 В главное меню | `back_to_main` | `back_to_main()` | ✅ |

### Меню и фильтры
| Кнопка | callback_data | Обработчик | Статус |
|--------|--------------|------------|--------|
| 🔍 Фильтры | `diet_filter` | `show_diet_filter()` | ✅ |
| diet_toggle_{key} | `diet_toggle_*` | `toggle_diet()` | ✅ |
| 🔍 Применить | `diet_apply` | `apply_diet_filter()` | ✅ |
| ❌ Сбросить | `diet_reset` | `reset_diet_filter()` | ✅ |

### Блюдо
| Кнопка | callback_data | Обработчик | Статус |
|--------|--------------|------------|--------|
| ➕ {dish} | `dish_{id}` | `show_dish_details()` | ✅ |
| ➕ В корзину | `add_to_cart_{id}` | `add_to_cart()` | ✅ |
| ⭐ В избранное | `favorite_{id}` | `toggle_favorite()` | ✅ |
| 🔄 Заказать | `quick_order_{id}` | `quick_order()` | ✅ |

### Корзина
| Кнопка | callback_data | Обработчик | Статус |
|--------|--------------|------------|--------|
| 📝 Оформить заказ | `checkout` | `checkout_handler()` | ✅ |
| 🗑️ Очистить корзину | `clear_cart` | `clear_cart_handler()` | ✅ |
| 💳 Оплатить | `pay_order` | `pay_order_handler()` | ✅ |
| ✅ Подтвердить оплату | `confirm_payment` | `confirm_payment_handler()` | ✅ |
| ❌ Отмена | `cancel_order` | `cancel_order_handler()` | ✅ |
| 🎁 Промокод | `enter_promo_order` | `enter_promo_handler()` | ✅ |
| 🎯 Использовать баллы | `use_points_{n}` | `use_points_handler()` | ✅ |

### Бронирование
| Кнопка | callback_data | Обработчик | Статус |
|--------|--------------|------------|--------|
| 📅 Забронировать столик | `reserve_new` | `start_reservation()` | ✅ |
| 📋 Мои бронирования | `reserve_my` | `my_reservations()` | ✅ |
| loc_* | `loc_*` | `select_location()` | ✅ |
| seats_* | `seats_*` | `select_seats()` | ✅ |
| date_* | `date_*` | `select_date()` | ✅ |
| time_* | `time_*` | `select_time()` | ✅ |
| table_* | `table_*` | `select_table()` | ✅ |
| reserve_confirm_* | `reserve_confirm_*` | `confirm_reservation()` | ✅ |
| reserve_cancel | `reserve_cancel` | `cancel_reservation_flow()` | ✅ |
| no_slots | `no_slots` | `no_slots()` | ✅ |

### Конструктор блюд
| Кнопка | callback_data | Обработчик | Статус |
|--------|--------------|------------|--------|
| 🛠️ Создать блюдо | `constructor_start` | `start_constructor()` | ✅ |
| tmpl_* | `tmpl_*` | `select_template()` | ✅ |
| ing_* | `ing_*` | `select_single_ingredient()` / `toggle_topping()` / `toggle_sauce()` | ✅ |
| ing_done | `ing_done` | `ingredient_done()` | ✅ |
| ing_skip | `ing_skip` | `skip_category()` | ✅ |
| constructor_to_cart | `constructor_to_cart` | `add_to_cart()` | ✅ |
| constructor_edit | `constructor_edit` | `edit_dish()` | ✅ |
| constructor_cancel | `constructor_cancel` | `cancel_constructor()` | ✅ |
| constructor_back | `constructor_back` | `back_in_constructor()` | ✅ |

### Админ-панель
| Кнопка | callback_data | Обработчик | Статус |
|--------|--------------|------------|--------|
| admin_panel | `admin_panel` | `admin_panel()` | ✅ |
| admin_orders | `admin_orders` | `admin_orders()` | ✅ |
| admin_menu | `admin_menu` | `admin_menu()` | ✅ |
| admin_add_dish | `admin_add_dish` | `admin_add_dish()` | ✅ |
| admin_edit_dish | `admin_edit_dish` | `admin_edit_dish()` | ✅ |
| admin_delete_dish | `admin_delete_dish` | `admin_delete_dish()` | ✅ |
| admin_dish_delete_* | `admin_dish_delete_*` | `confirm_delete_dish()` | ✅ |
| admin_couriers | `admin_couriers` | `admin_couriers()` | ✅ |
| admin_add_courier | `admin_add_courier` | `admin_add_courier()` | ✅ |
| admin_promo | `admin_promo` | `admin_promo()` | ✅ |
| admin_create_promo | `admin_create_promo` | `admin_create_promo()` | ✅ |
| admin_analytics | `admin_analytics` | `admin_analytics()` | ✅ |
| admin_kitchen_load | `admin_kitchen_load` | `admin_kitchen_load()` | ✅ |
| admin_broadcast | `admin_broadcast` | `admin_broadcast()` | ✅ |
| admin_reservations | `admin_reservations` | `admin_reservations()` | ✅ |
| admin_reserve_detail_* | `admin_reserve_detail_*` | `reservation_detail()` | ✅ |
| admin_reserve_confirm_* | `admin_reserve_confirm_*` | `confirm_reservation()` | ✅ |
| admin_reserve_reject_* | `admin_reserve_reject_*` | `reject_reservation()` | ✅ |
| admin_reserve_comment_* | `admin_reserve_comment_*` | `start_add_comment()` | ✅ |
| toggle_slot_* | `toggle_slot_*` | `toggle_slot()` | ✅ |

---

## ⚠️ Найденные проблемы

### 1. Дублирование обработчиков
**Файлы:** `bot.py` и `app/handlers/*.py`

Одни и те же callback_data обрабатываются в двух местах:
- `menu` → есть в `bot.py` и `app/handlers/user_handlers.py`
- `back_to_main` → есть в `bot.py` и `app/handlers/common_handler.py`
- `cart`, `checkout`, `pay_order` → есть в `bot.py` и `app/handlers/cart_handler.py`

**Решение:** Выбрать одну архитектуру (рекомендуется modular `app/`) и удалить дубли из `bot.py`.

### 2. Порядок регистрации роутеров
В `main.py` роутеры регистрируются в правильном порядке:
```python
dp.include_router(user_router)      # Специфичные
dp.include_router(cart_router)
dp.include_router(admin_router)
dp.include_router(reservation_router)
dp.include_router(admin_reservation_router)
dp.include_router(constructor_router)
dp.include_router(common_router)    # Fallback — в конце!
```

**Важно:** `common_router` с `back_to_main` должен быть последним!

### 3. Состояния (States)
**Проблема:** В `bot.py` используется `OrderState`, в `app/` — `UserStates`.

**Решение:** Унифицировать состояния в `app/states.py`.

---

## ✅ Рекомендации

### Критичные
1. **Удалить дублирующие обработчики из `bot.py`** — оставить только `app/handlers/`
2. **Проверить порядок роутеров** — `common_router` должен быть последним
3. **Унифицировать States** — использовать только `UserStates` из `app/states.py`

### Важные
4. Добавить проверку на админа во все admin_* обработчики ✅ (уже есть)
5. Добавить обработку ошибок `MessageNotModified` ✅ (уже есть)
6. Проверить все keyboard builders на `.adjust()` ✅

### Опциональные
7. Добавить иконки ко всем кнопкам
8. Добавить pagination для длинных списков (заказы, меню)
9. Добавить inline search для меню

---

## 📊 Статистика

- **Всего callback_data:** ~70
- **Обработчиков:** ~70
- **Клавиатур:** 15+
- **Дубликатов:** 3 (критично)
- **Ошибок:** 0 ✅

---

## 🎯 Итог

**Навигация работает корректно!** Все кнопки имеют обработчики.

**Главная проблема:** дублирование кода между `bot.py` и `app/handlers/`.

**Рекомендация:** Полностью перейти на модульную структуру `app/` и удалить обработчики из `bot.py`.
