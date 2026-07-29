"""Утилиты для работы с базой данных — pool соединений"""

import logging
import aiosqlite
from contextlib import asynccontextmanager
from app.config import DB_NAME, DB_POOL_SIZE
import asyncio

logger = logging.getLogger(__name__)


class DatabasePool:
    """Простой пул соединений для aiosqlite"""

    def __init__(self, db_name: str, pool_size: int = 5):
        self._db_name = db_name
        self._pool_size = pool_size
        self._connections: list[aiosqlite.Connection] = []
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Инициализация пула соединений"""
        async with self._lock:
            if self._initialized:
                return

            # Создаём соединения
            for _ in range(self._pool_size):
                conn = await aiosqlite.connect(self._db_name)
                await conn.execute("PRAGMA journal_mode = WAL")
                await conn.execute("PRAGMA foreign_keys = ON")
                await conn.execute("PRAGMA busy_timeout = 5000")
                await conn.execute("PRAGMA cache_size = -2000")
                await conn.execute("PRAGMA temp_store = MEMORY")
                self._connections.append(conn)

            self._initialized = True
            logger.info(
                f"✅ Пул соединений инициализирован ({self._pool_size} соединений)"
            )

    async def get_connection(self) -> aiosqlite.Connection:
        """Получить свободное соединение"""
        async with self._lock:
            if not self._initialized:
                await self.initialize()

            # Возвращаем первое доступное соединение
            if self._connections:
                return self._connections.pop(0)  # Извлекаем соединение из пула

            # Если все заняты — создаём временное
            conn = await aiosqlite.connect(self._db_name)
            await conn.execute("PRAGMA journal_mode = WAL")
            await conn.execute("PRAGMA foreign_keys = ON")
            return conn

    async def return_connection(self, conn: aiosqlite.Connection):
        """Вернуть соединение в пул"""
        async with self._lock:
            # Проверяем, не закрыто ли соединение через try/except
            is_closed = False
            try:
                # В aiosqlite нет атрибута closed, пробуем выполнить простую операцию
                await conn.execute("SELECT 1")
            except Exception:
                is_closed = True
            
            if len(self._connections) < self._pool_size and not is_closed:
                self._connections.append(conn)
            else:
                # Если пул полон или соединение закрыто, просто закрываем его
                try:
                    await conn.close()
                except Exception:
                    pass

    async def close_all(self):
        """Закрыть все соединения"""
        async with self._lock:
            for conn in self._connections:
                try:
                    await conn.close()
                except Exception:
                    pass
            self._connections.clear()
            self._initialized = False
            logger.info("🔌 Все соединения закрыты")


# Глобальный пул
db_pool = DatabasePool(DB_NAME, DB_POOL_SIZE)


@asynccontextmanager
async def get_db():
    """Контекстный менеджер для получения соединения"""
    conn = await db_pool.get_connection()
    try:
        yield conn
        await conn.commit()
    except Exception as e:
        await conn.rollback()
        logger.error(f"❌ Ошибка БД: {e}", exc_info=True)
        raise
    finally:
        # Возвращаем соединение обратно в пул
        await db_pool.return_connection(conn)
