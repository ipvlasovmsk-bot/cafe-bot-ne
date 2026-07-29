# Изменения для Таиланда: валюта ฿ и тайское время (UTC+7)

## Выполненные изменения

### 1. Созданы новые файлы

#### `app/utils/thai_time.py`
Утилита для работы с тайским временем и валютой:
- `get_thailand_time()` - получение текущего времени UTC+7
- `format_thailand_time()` - форматирование времени в тайском часовом поясе
- `format_thailand_date()` - форматирование даты в тайском часовом поясе
- `format_price()` - форматирование цены с символом валюты (฿)

#### `app/config.py`
Добавлены новые настройки:
```python
TIMEZONE_OFFSET = 7  # UTC+7 для Таиланда
CURRENCY_SYMBOL = "฿"  # Тайский бат
CURRENCY_NAME = "THB"  # Код валюты
```

### 2. Обновлённые файлы

Все следующие файлы обновлены с использованием:
- `format_price()` вместо `"{price}₽"`
- `format_thailand_time()` вместо `.strftime()` для времени

#### Основные обработчики:
- ✅ `app/handlers/user_handlers.py`
- ✅ `app/handlers/cart_handler.py`
- ✅ `app/handlers/admin_handler.py`
- ✅ `app/handlers/admin_order_handler.py`
- ✅ `app/handlers/admin_check_handler.py`
- ✅ `app/handlers/payment_check_handler.py`
- ✅ `app/handlers/dish_constructor_handler.py`

#### Сервисы и утилиты:
- ✅ `app/utils/thai_time.py` (новый файл)

#### Главный файл:
- ✅ `main.py`

## Форматы времени

Теперь все времена отображаются в часовом поясе Таиланда (UTC+7):

- **Дата и время заказа**: `25.01 14:30` (DD.MM HH:MM)
- **Дата**: `25.01.2025` (DD.MM.YYYY)
- **Время готовности**: `14:30` (HH:MM)

## Валюта

Все цены теперь отображаются в тайских батах (฿):

- **Пример**: `1500฿` вместо `1500₽`
- **Скидки**: `Скидка 200฿` вместо `Скидка 200₽`
- **Итого**: `Итого: 1500฿` вместо `Итого: 1500₽`

## Оставшиеся файлы для обновления

Следующие файлы ещё содержат `₽` и могут потребовать обновления:

### Старая версия бота:
- `bot.py` - старая монолитная версия (если не используется, можно не обновлять)

### Клавиатуры:
- `app/keyboards/main.py` - клавиатуры с ценами

### Сервисы:
- `app/services/dish_constructor.py` - логика конструктора блюд
- `app/services/delivery.py` - расчёт доставки

### Документация:
- `README.md` - примеры в документации
- `ORDER_MANAGEMENT.md` - примеры заказов
- `QR_PAYMENT_SETUP.md` - примеры оплаты

## Как использовать в новом коде

### Импортируйте утилиты:
```python
from app.utils.thai_time import format_price, format_thailand_time, format_thailand_date
from app.config import CURRENCY_SYMBOL
```

### Форматируйте цены:
```python
# Вместо: f"Цена: {price}₽"
# Используйте:
text = f"Цена: {format_price(price)}"  # 1500฿
text = f"Цена: {format_price(price, '€')}"  # 1500€ (если нужна другая валюта)
```

### Форматируйте время:
```python
# Вместо: dt.strftime("%d.%m %H:%M")
# Используйте:
text = f"Время: {format_thailand_time(dt, '%d.%m %H:%M')}"  # 25.01 14:30
text = f"Дата: {format_thailand_date(dt, '%d.%m.%Y')}"  # 25.01.2025
```

### Получите текущее время Таиланда:
```python
from app.utils.thai_time import get_thailand_time

thailand_now = get_thailand_time()
print(f"Сейчас в Таиланде: {thailand_now}")
```

## Тестирование

Проверьте работу изменений:
1. Запустите бота
2. Откройте меню - цены должны быть в ฿
3. Оформите заказ - время должно быть в UTC+7
4. Проверьте админ-панель - все суммы и времена должны быть правильными

## Примечания

- Часовой пояс Таиланда фиксированный (UTC+7), без перехода на летнее время
- Валюта может быть изменена в `app/config.py` через `CURRENCY_SYMBOL`
- Все даты и времена в БД сохраняются в ISO формате, конвертация происходит только при отображении
