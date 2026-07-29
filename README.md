# Cafe Bot — Telegram-бот для кафе/ресторана

Полнофункциональный бот с доставкой, программой лояльности, админ-панелью и аналитикой.

## 🚀 Быстрый старт

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 2. Настройка

Скопируйте `.env.example` в `.env` и настройте:

```bash
cp .env.example .env
```

Минимум — проверьте `BOT_TOKEN` и `ADMIN_IDS`.

### 3. Запуск

**Обычный режим (polling):**
```bash
python main.py
```

**С автоперезапуском и бэкапами:**
```bash
python run.py
```

**С мониторингом (в отдельном терминале):**
```bash
python monitor.py
```

---

## 🐳 Docker

```bash
# Запуск бота
docker-compose up -d bot

# С мониторингом
docker-compose up -d bot monitor

# Логи
docker-compose logs -f bot
```

---

## 📋 Что умеет бот

### Пользователь
| Функция | Описание |
|---|---|
| `/start` | Регистрация + 100 приветственных баллов |
| 🍽️ Меню | Фильтрация по диетам и аллергенам |
| 🛒 Корзина | Добавление блюд, расчёт доставки |
| 📝 Оформление | Адрес → Время → Оплата |
| 💎 Лояльность | 4 уровня, кешбэк 3-10% |
| 🎁 Промокоды | %, фиксированная скидка, бесплатная доставка |
| ⭐ Избранное | Быстрый повторный заказ |
| 🤖 Рекомендации | На основе истории заказов |
| 📦 История заказов | Последние 10 заказов |
| 👤 Профиль | Редактирование данных |

### Администратор
| Функция | Описание |
|---|---|
| 📋 Заказы | Просмотр всех заказов |
| 🍽️ Меню | CRUD блюд |
| 🚚 Курьеры | Управление курьерами |
| 🎁 Промокоды | Создание промокодов |
| 📊 Аналитика | Дашборд в реальном времени |
| 🏢 Кухня | Блокировка слотов |
| 📢 Рассылка | Массовая отправка сообщений |

---

## 🏗️ Архитектура

```
cafe-bot/
├── main.py                 # Запуск (polling режим)
├── run.py                  # Process manager + автобэкапы
├── webhook_server.py       # Запуск (webhook режим)
├── monitor.py              # Мониторинг работоспособности
├── bot.py                  # Старая версия (монолит)
├── docker-compose.yml      # Docker конфигурация
├── Dockerfile              # Образ бота
├── nginx.conf              # Nginx для webhook
│
├── app/
│   ├── config.py           # Конфигурация
│   ├── database.py         # Пул соединений
│   ├── init_db.py          # Создание таблиц
│   ├── migrations.py       # Миграции БД
│   ├── states.py           # FSM состояния
│   │
│   ├── handlers/
│   │   ├── user_handler.py    # Пользовательские
│   │   ├── cart_handler.py    # Корзина/заказ
│   │   ├── admin_handler.py   # Админ-панель
│   │   └── common_handler.py  # Навигация
│   │
│   ├── services/
│   │   ├── loyalty.py      # Лояльность, рефералы
│   │   ├── kitchen.py      # Таймеры кухни
│   │   ├── delivery.py     # Зоны доставки
│   │   └── analytics.py    # ML, аналитика
│   │
│   ├── middleware/
│   │   └── rate_limit.py   # Rate limiting
│   │
│   ├── keyboards/
│   │   └── main.py         # Клавиатуры
│   │
│   └── utils/
│       └── validators.py   # Валидация ввода
│
└── tests/
    └── test_bot.py         # Тесты
```

---

## 🔧 Режимы запуска

### Polling (разработка / небольшой проект)
```bash
python main.py
```
- Простой, не нужен сервер
- Не подходит для >100 пользователей

### Webhook (production)
```bash
# Нужен публичный HTTPS URL
python webhook_server.py
```
- Мгновенная доставка обновлений
- Требует HTTPS (ngrok, Let's Encrypt)

### Process Manager (рекомендуемый)
```bash
python run.py
```
- Автоперезапуск при падении (до 10 раз за 5 мин)
- Автобэкап БД каждый час
- Очистка старых бэкапов (7 дней)

---

## 📊 Миграции БД

```python
# Применить миграции (автоматически при старте)
from app.migrations import run_migrations
await run_migrations()

# Откатить последнюю миграцию
from app.migrations import rollback_migration
await rollback_migration()

# Откатить до конкретной версии
await rollback_migration(target_version=1)
```

Добавление новой миграции — добавить в `app/migrations.py`:
```python
Migration(
    version=4,
    name="description",
    up_sql="ALTER TABLE ...",
    down_sql="..."
)
```

---

## 🧪 Тесты

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```

---

## 🔒 Безопасность

- ✅ `.env` в `.gitignore` — токены не попадают в репозиторий
- ✅ Rate limiting — защита от спама
- ✅ Валидация ввода — телефон, email, адрес
- ✅ Админ-проверка — только ADMIN_IDS имеют доступ
- ✅ Параметризованные SQL-запросы — защита от инъекций

---

## 📝 Логи

| Файл | Что содержит |
|---|---|
| `bot.log` | Основной лог бота |
| `process_manager.log` | Рестарты, бэкапы |
| `monitor.log` | Проверки доступности |

---

## ⚙️ Переменные окружения

| Переменная | Описание | По умолчанию |
|---|---|---|
| `BOT_TOKEN` | Токен от @BotFather | — |
| `ADMIN_IDS` | ID администраторов (через запятую) | — |
| `PROXY_URL` | Прокси для доступа к Telegram | `None` |
| `LOG_LEVEL` | Уровень логирования | `INFO` |
| `WEBHOOK_URL` | URL webhook (для webhook режима) | — |
| `MONITOR_INTERVAL` | Интервал проверки (сек) | `60` |

---

## 🛠️ Устранение проблем

### Бот не подключается к Telegram
1. Проверьте интернет: `ping api.telegram.org`
2. Попробуйте другой интернет (мобильная точка)
3. Добавьте прокси в `.env`: `PROXY_URL=http://proxy:port`

### Бот упал
Process manager (`run.py`) автоматически перезапустит его. Проверьте `bot.log`.

### База данных повреждена
Бэкапы находятся в `backups/`. Восстановите:
```bash
cp backups/cafe_bot_20250101_120000.db cafe_ecosystem.db
```

---

## 📄 Лицензия

MIT
