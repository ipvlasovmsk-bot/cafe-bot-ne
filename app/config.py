"""Конфигурация приложения"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в .env")

ADMIN_IDS = [int(id.strip()) for id in os.getenv("ADMIN_IDS", "").split(",") if id.strip()]

# Часовой пояс и валюта
TIMEZONE_OFFSET = 7  # UTC+7 для Таиланда
CURRENCY_SYMBOL = "฿"  # Тайский бат
CURRENCY_NAME = "THB"  # Код валюты

# Кафе
CAFE_ADDRESS = os.getenv("CAFE_ADDRESS", "105, Bogatyr - Russian food, Kathu District, Phuket, Thailand")
CAFE_PHONE = os.getenv("CAFE_PHONE", "+7 (999) 000-00-00")
PAYMENT_CARD = os.getenv("PAYMENT_CARD", "2200 1111 2222 3333")
PAYMENT_QR_PATH = os.getenv("PAYMENT_QR_PATH", "payment_qr.jpg")  # Путь к фото QR-кода
CAFE_LAT = float(os.getenv("CAFE_LAT", "7.9950"))  # Kathu District, Phuket
CAFE_LON = float(os.getenv("CAFE_LON", "98.3250"))  # Kathu District, Phuket

# Лояльность
LOYALTY_BRONZE_THRESHOLD = 5000
LOYALTY_SILVER_THRESHOLD = 15000
LOYALTY_GOLD_THRESHOLD = 50000
LOYALTY_CASHBACK_BRONZE = 0.03
LOYALTY_CASHBACK_SILVER = 0.05
LOYALTY_CASHBACK_GOLD = 0.10
REFERRAL_BONUS = 500

# Кухня
KITCHEN_CAPACITY_PER_HOUR = 10
PREP_TIME_BASE = 20
PREP_TIME_PER_ITEM = 10

# База данных
DB_NAME = "cafe_ecosystem.db"
DB_POOL_SIZE = 5  # Максимум соединений в пуле

# Прокси (если Telegram заблокирован)
# Формат: http://user:pass@proxy:port или socks5://user:pass@proxy:port
# Оставьте None если прокси не нужен
PROXY_URL = os.getenv("PROXY_URL")  # Пример: "http://127.0.0.1:1080"

# Логирование
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = "bot.log"
