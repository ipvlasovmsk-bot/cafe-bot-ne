"""Доставка — зоны, расчёт стоимости, курьеры"""
import logging
import json
from typing import Optional, Tuple, List
from datetime import datetime

import aiosqlite
from app.utils.thai_time import format_price

logger = logging.getLogger(__name__)


class DeliveryManager:
    """Управление доставкой"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    @staticmethod
    def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Формула Haversine для расстояния в км"""
        R = 6371
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lat = math.radians(lat2 - lat1)
        delta_lon = math.radians(lon2 - lon1)

        a = (math.sin(delta_lat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    @staticmethod
    def is_point_in_zone(lat: float, lon: float, polygon: list[tuple[float, float]]) -> bool:
        """Ray casting algorithm"""
        n = len(polygon)
        inside = False
        p1x, p1y = polygon[0]

        for i in range(n + 1):
            p2x, p2y = polygon[i % n]
            if lon > min(p1y, p2y):
                if lon <= max(p1y, p2y):
                    if lat <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (lon - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or lat <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y

        return inside

    async def get_zone_for_address(self, lat: float, lon: float) -> Optional[dict]:
        """Определение зоны доставки по координатам"""
        cursor = await self.db.execute(
            "SELECT * FROM delivery_zones WHERE is_active = 1"
        )
        zones = await cursor.fetchall()

        for zone in zones:
            try:
                polygon = json.loads(zone[5])
                if self.is_point_in_zone(lat, lon, polygon):
                    return {
                        'id': zone[0],
                        'name': zone[1],
                        'min_order': zone[2],
                        'delivery_cost': zone[3],
                        'free_from': zone[4]
                    }
            except (json.JSONDecodeError, IndexError) as e:
                logger.warning(f"Ошибка парсинга полигона зоны {zone[0]}: {e}")

        return None

    async def calculate_delivery_cost(self, lat: float, lon: float, order_sum: int) -> dict:
        """Расчёт стоимости доставки"""
        zone = await self.get_zone_for_address(lat, lon)

        if not zone:
            return {
                'available': False,
                'reason': 'Адрес вне зоны доставки'
            }

        if order_sum < zone['min_order']:
            return {
                'available': False,
                'reason': f"Минимальная сумма заказа: {format_price(zone['min_order'])}"
            }

        cost = 0 if order_sum >= zone['free_from'] else zone['delivery_cost']

        return {
            'available': True,
            'zone_name': zone['name'],
            'cost': cost,
            'free_from': zone['free_from'],
            'min_order': zone['min_order']
        }

    async def find_nearest_courier(self, lat: float, lon: float) -> Optional[int]:
        """Поиск ближайшего свободного курьера"""
        cursor = await self.db.execute(
            "SELECT id, current_lat, current_lon FROM couriers "
            "WHERE status = 'online' AND last_update > datetime('now', '-5 minutes')"
        )
        couriers = await cursor.fetchall()

        if not couriers:
            return None

        min_distance = float('inf')
        nearest_id = None

        for courier in couriers:
            try:
                dist = self.calculate_distance(lat, lon, courier[1], courier[2])
                if dist < min_distance:
                    min_distance = dist
                    nearest_id = courier[0]
            except (TypeError, ValueError):
                continue

        return nearest_id


async def init_default_zones(db: aiosqlite.Connection):
    """Инициализация зон доставки по умолчанию (если пусто)"""
    cursor = await db.execute("SELECT COUNT(*) FROM delivery_zones")
    count = (await cursor.fetchone())[0]

    if count > 0:
        return  # Зоны уже есть

    # Создаём зону по умолчанию (круг вокруг кафе, ~5 км)
    # Для простоты — квадратный полигон
    center_lat = 55.7558
    center_lon = 37.6173
    delta = 0.045  # ~5 км

    polygon = [
        (center_lat + delta, center_lon - delta),
        (center_lat + delta, center_lon + delta),
        (center_lat - delta, center_lon + delta),
        (center_lat - delta, center_lon - delta),
    ]

    await db.execute(
        "INSERT INTO delivery_zones (name, min_order, delivery_cost, free_from, polygon, is_active) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        ("Центральная", 500, 199, 1500, json.dumps(polygon))
    )
    logger.info("✅ Создана зона доставки по умолчанию")
