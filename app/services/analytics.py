"""ML-рекомендации и аналитика"""
import logging
import json
from datetime import datetime
from typing import List, Dict, Optional

import aiosqlite

from app.config import KITCHEN_CAPACITY_PER_HOUR

logger = logging.getLogger(__name__)


class MLRecommendationEngine:
    """Простая рекомендательная система на основе истории"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_recommendations(self, user_id: int, limit: int = 5) -> List[Dict]:
        """Персональные рекомендации"""
        cursor = await self.db.execute(
            "SELECT items FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 10",
            (user_id,)
        )
        orders = await cursor.fetchall()

        if not orders:
            return await self._get_popular_dishes(limit)

        dish_counts = {}
        category_counts = {}

        for order in orders:
            try:
                items = json.loads(order[0])
            except (json.JSONDecodeError, TypeError):
                continue

            for item in items:
                dish_id = item.get('dish_id')
                category = item.get('category', 'unknown')
                if dish_id:
                    dish_counts[dish_id] = dish_counts.get(dish_id, 0) + 1
                category_counts[category] = category_counts.get(category, 0) + 1

        favorite_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:2]
        favorite_categories = [cat[0] for cat in favorite_categories]
        excluded_dishes = list(dish_counts.keys())

        if not favorite_categories:
            return await self._get_popular_dishes(limit)

        try:
            placeholders_cats = ','.join(['?' for _ in favorite_categories])
            placeholders_excl = ','.join(['?' for _ in excluded_dishes]) if excluded_dishes else '0'

            query = (
                f"SELECT * FROM menu WHERE category IN ({placeholders_cats}) "
                f"AND id NOT IN ({placeholders_excl}) AND is_active = 1 "
                f"ORDER BY popularity_score DESC, rating DESC LIMIT ?"
            )
            params = favorite_categories + (excluded_dishes if excluded_dishes else []) + [limit]

            cursor = await self.db.execute(query, params)
            dishes = await cursor.fetchall()
            return [self._dish_to_dict(dish) for dish in dishes]
        except Exception as e:
            logger.error(f"Ошибка получения рекомендаций: {e}")
            return await self._get_popular_dishes(limit)

    async def _get_popular_dishes(self, limit: int) -> List[Dict]:
        cursor = await self.db.execute(
            "SELECT * FROM menu WHERE is_active = 1 ORDER BY popularity_score DESC, rating DESC LIMIT ?",
            (limit,)
        )
        dishes = await cursor.fetchall()
        return [self._dish_to_dict(dish) for dish in dishes]

    def _dish_to_dict(self, dish: tuple) -> Dict:
        return {
            'id': dish[0],
            'name': dish[1],
            'description': dish[2],
            'price': dish[3],
            'category': dish[6],
            'rating': dish[12] if len(dish) > 12 else 5.0,
            'diet_tags': json.loads(dish[10]) if len(dish) > 10 and dish[10] else []
        }

    async def predict_demand(self, target_date) -> Dict[str, int]:
        """Прогноз спроса"""
        weekday = target_date.weekday()

        cursor = await self.db.execute(
            "SELECT AVG(metric_value) FROM analytics WHERE metric_type = 'orders_count' "
            "AND strftime('%w', date) = ?",
            (str(weekday),)
        )
        avg_orders = (await cursor.fetchone())[0] or 50

        cursor = await self.db.execute(
            "SELECT SUM(impact_factor) FROM events WHERE date = ?",
            (target_date.isoformat(),)
        )
        event_factor = (await cursor.fetchone())[0] or 1.0

        prediction = int(avg_orders * event_factor)

        distribution = {
            'pizza': 0.3, 'burger': 0.25, 'salad': 0.15, 'pasta': 0.2, 'drinks': 0.1
        }

        return {
            'total': prediction,
            'by_category': {cat: int(prediction * dist) for cat, dist in distribution.items()}
        }


class AnalyticsManager:
    """Аналитика и дашборд"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def log_event(self, metric_type: str, value: float, details: Dict | None = None):
        now = datetime.now()
        await self.db.execute(
            "INSERT INTO analytics (date, hour, metric_type, metric_value, details) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                now.strftime("%Y-%m-%d"),
                now.hour,
                metric_type,
                value,
                json.dumps(details) if details else None
            )
        )

    async def get_dashboard_data(self) -> Dict:
        """Real-time данные для дашборда"""
        today = datetime.now().strftime("%Y-%m-%d")

        cursor = await self.db.execute(
            "SELECT COUNT(*), COALESCE(SUM(total_price), 0) FROM orders WHERE DATE(created_at) = ?",
            (today,)
        )
        today_orders, today_revenue = await cursor.fetchone()

        cursor = await self.db.execute(
            "SELECT COUNT(*) FROM orders WHERE status IN "
            "('new', 'accepted', 'cooking', 'prep', 'assembly')"
        )
        in_progress = (await cursor.fetchone())[0]

        cursor = await self.db.execute(
            "SELECT AVG((julianday(actual_ready_time) - julianday(created_at)) * 24 * 60) "
            "FROM orders WHERE DATE(created_at) = ? AND actual_ready_time IS NOT NULL",
            (today,)
        )
        avg_prep_time = (await cursor.fetchone())[0] or 0

        cursor = await self.db.execute(
            "SELECT items FROM orders WHERE DATE(created_at) = ?", (today,)
        )
        all_items = await cursor.fetchall()

        dish_counts = {}
        for order_items in all_items:
            try:
                items = json.loads(order_items[0])
                for item in items:
                    name = item.get('dish_name', 'Unknown')
                    dish_counts[name] = dish_counts.get(name, 0) + 1
            except (json.JSONDecodeError, TypeError):
                continue

        top_dishes = sorted(dish_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        kitchen_load = await self._get_current_kitchen_load()

        return {
            'today_orders': today_orders or 0,
            'today_revenue': today_revenue or 0,
            'in_progress': in_progress,
            'avg_prep_time': round(avg_prep_time, 1),
            'top_dishes': top_dishes,
            'kitchen_load': kitchen_load
        }

    async def _get_current_kitchen_load(self) -> Dict:
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        hour = now.hour

        cursor = await self.db.execute(
            "SELECT current_load, max_capacity FROM kitchen_load WHERE date = ? AND hour = ?",
            (date_str, hour)
        )
        row = await cursor.fetchone()

        if not row:
            return {'current': 0, 'max': KITCHEN_CAPACITY_PER_HOUR, 'percent': 0}

        current, max_cap = row
        return {
            'current': current,
            'max': max_cap,
            'percent': int((current / max_cap) * 100) if max_cap > 0 else 0
        }
