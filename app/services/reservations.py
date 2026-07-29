"""Сервис управления бронированием столиков"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import aiosqlite

from app.models import ReservationStatus, TableLocation

logger = logging.getLogger(__name__)

# Доступные слоты времени для бронирования
RESERVATION_TIME_SLOTS = [
    "10:00", "11:00", "12:00", "13:00", "14:00",
    "15:00", "16:00", "17:00", "18:00", "19:00",
    "20:00", "21:00", "22:00"
]

# Локация столика — человекочитаемое название
LOCATION_NAMES = {
    TableLocation.WINDOW: "🪟 У окна",
    TableLocation.HALL: "🏛️ Центр зала",
    TableLocation.CORNER: "🛋️ Уютный уголок",
    TableLocation.VIP: "👑 VIP-зона",
    TableLocation.TERRACE: "🌿 Терраса",
}


class ReservationService:
    """Управление бронированием столиков"""

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def get_active_tables(self, location: TableLocation | None = None,
                                 min_seats: int = 0) -> list[dict]:
        """Получить список доступных столиков"""
        query = "SELECT id, name, seats, location, is_active FROM cafe_tables WHERE is_active = 1"
        params: list = []

        if min_seats > 0:
            query += " AND seats >= ?"
            params.append(min_seats)

        if location:
            query += " AND location = ?"
            params.append(location.value)

        query += " ORDER BY seats ASC, id ASC"
        cursor = await self.db.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def get_available_tables(self, date: str, time: str,
                                    min_seats: int = 0) -> list[dict]:
        """Получить столики, свободные на указанное время"""
        # Берём все активные столики с нужным кол-вом мест
        all_tables = await self.get_active_tables(min_seats=min_seats)

        # Находим уже занятые
        cursor = await self.db.execute(
            """SELECT table_id FROM table_reservations
               WHERE reservation_date = ? AND reservation_time = ?
                 AND status IN ('pending', 'confirmed')""",
            (date, time)
        )
        busy = {row[0] for row in await cursor.fetchall()}

        return [t for t in all_tables if t["id"] not in busy]

    async def get_available_time_slots(self, date: str, table_id: int) -> list[str]:
        """Получить свободные слоты времени для столика на дату"""
        cursor = await self.db.execute(
            """SELECT reservation_time FROM table_reservations
               WHERE reservation_date = ? AND table_id = ?
                 AND status IN ('pending', 'confirmed')""",
            (date, table_id)
        )
        busy = {row[0] for row in await cursor.fetchall()}
        return [slot for slot in RESERVATION_TIME_SLOTS if slot not in busy]

    async def create_reservation(self, user_id: int, table_id: int,
                                  date: str, time: str, guest_count: int,
                                  guest_name: str, guest_phone: str,
                                  special_requests: str = "") -> int:
        """Создать бронирование (статус — pending)"""
        now = datetime.now().isoformat()
        cursor = await self.db.execute(
            """INSERT INTO table_reservations
               (user_id, table_id, reservation_date, reservation_time, guest_count,
                guest_name, guest_phone, special_requests, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (user_id, table_id, date, time, guest_count, guest_name,
             guest_phone, special_requests, now, now)
        )
        await self.db.commit()
        return cursor.lastrowid

    async def get_user_reservations(self, user_id: int,
                                     limit: int = 10) -> list[dict]:
        """Получить бронирования пользователя"""
        cursor = await self.db.execute(
            """SELECT r.id, r.reservation_date, r.reservation_time, r.guest_count,
                      r.status, r.guest_name, r.guest_phone, r.special_requests,
                      r.admin_comment, r.created_at,
                      t.name as table_name, t.seats, t.location
               FROM table_reservations r
               JOIN cafe_tables t ON r.table_id = t.id
               WHERE r.user_id = ?
               ORDER BY r.reservation_date DESC, r.reservation_time DESC
               LIMIT ?""",
            (user_id, limit)
        )
        columns = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def get_reservation(self, reservation_id: int) -> Optional[dict]:
        """Получить бронирование по ID"""
        cursor = await self.db.execute(
            """SELECT r.*, t.name as table_name, t.seats, t.location,
                      u.username, u.first_name
               FROM table_reservations r
               JOIN cafe_tables t ON r.table_id = t.id
               JOIN users u ON r.user_id = u.user_id
               WHERE r.id = ?""",
            (reservation_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, row))

    async def update_reservation_status(self, reservation_id: int,
                                         status: ReservationStatus,
                                         admin_comment: str = "") -> bool:
        """Обновить статус бронирования"""
        now = datetime.now().isoformat()
        await self.db.execute(
            """UPDATE table_reservations
               SET status = ?, admin_comment = ?, updated_at = ?
               WHERE id = ?""",
            (status.value, admin_comment, now, reservation_id)
        )
        await self.db.commit()
        return True

    async def get_all_reservations(self, status: str | None = None,
                                    date: str | None = None,
                                    limit: int = 20) -> list[dict]:
        """Получить все бронирования (для админа)"""
        query = """SELECT r.*, t.name as table_name, t.seats, t.location,
                          u.username, u.first_name
                   FROM table_reservations r
                   JOIN cafe_tables t ON r.table_id = t.id
                   JOIN users u ON r.user_id = u.user_id
                   WHERE 1=1"""
        params: list = []

        if status:
            query += " AND r.status = ?"
            params.append(status)
        if date:
            query += " AND r.reservation_date = ?"
            params.append(date)

        query += " ORDER BY r.reservation_date DESC, r.reservation_time DESC LIMIT ?"
        params.append(limit)

        cursor = await self.db.execute(query, params)
        columns = [desc[0] for desc in cursor.description]
        rows = await cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    async def get_reservation_stats(self, date: str) -> dict:
        """Статистика бронирований на дату"""
        cursor = await self.db.execute(
            """SELECT status, COUNT(*) FROM table_reservations
               WHERE reservation_date = ?
               GROUP BY status""",
            (date,)
        )
        rows = await cursor.fetchall()
        stats = {}
        for status, count in rows:
            stats[status] = count

        # Всего мест на дату
        cursor = await self.db.execute(
            """SELECT COUNT(*) FROM cafe_tables WHERE is_active = 1"""
        )
        total_tables = (await cursor.fetchone())[0]

        # Занятых слотов на каждый час
        cursor = await self.db.execute(
            """SELECT reservation_time, COUNT(*) FROM table_reservations
               WHERE reservation_date = ? AND status IN ('pending', 'confirmed')
               GROUP BY reservation_time""",
            (date,)
        )
        busy_slots = dict(await cursor.fetchall())

        return {
            "total_tables": total_tables,
            "by_status": stats,
            "busy_slots": busy_slots,
        }
