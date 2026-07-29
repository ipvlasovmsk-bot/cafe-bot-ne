"""Process manager — автоматический рестарт бота при падении"""
import asyncio
import logging
import sys
import time
import signal
import os
from datetime import datetime

logger = logging.getLogger("process_manager")

# Настройки
MAX_RESTARTS = 10          # Максимум рестартов
RESTART_WINDOW = 300       # Окно времени в секундах (5 минут)
RESTART_DELAY = 3          # Задержка между рестартами (секунды)
BACKUP_INTERVAL = 3600     # Интервал бэкапа БД (1 час)


class ProcessManager:
    """Управление жизненным циклом бота"""

    def __init__(self):
        self.restarts = []
        self.running = True
        self.process = None
        self.backup_task = None

    def _should_restart(self) -> bool:
        """Проверка — можно ли ещё рестартить"""
        now = time.time()
        # Очищаем старые рестарты
        self.restarts = [t for t in self.restarts if now - t < RESTART_WINDOW]
        return len(self.restarts) < MAX_RESTARTS

    def _record_restart(self):
        """Записать факт рестарта"""
        self.restarts.append(time.time())

    async def _backup_database(self):
        """Периодический бэкап БД"""
        import shutil
        from app.config import DB_NAME

        backup_dir = "backups"
        os.makedirs(backup_dir, exist_ok=True)

        while self.running:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = os.path.join(backup_dir, f"cafe_bot_{timestamp}.db")

                if os.path.exists(DB_NAME):
                    shutil.copy2(DB_NAME, backup_file)

                    # Очистка старых бэкапов (> 7 дней)
                    self._cleanup_old_backups(backup_dir)

                    logger.info(f"[BACKUP] Создан бэкап: {backup_file}")

            except Exception as e:
                logger.error(f"[BACKUP] Ошибка: {e}")

            # Ждём следующий интервал
            await asyncio.sleep(BACKUP_INTERVAL)

    def _cleanup_old_backups(self, backup_dir: str):
        """Удаление бэкапов старше 7 дней"""
        import glob
        cutoff = time.time() - (7 * 86400)  # 7 дней

        for backup in glob.glob(os.path.join(backup_dir, "*.db")):
            if os.path.getmtime(backup) < cutoff:
                try:
                    os.remove(backup)
                    logger.info(f"[BACKUP] Удалён старый: {backup}")
                except OSError:
                    pass

    async def _run_bot(self):
        """Запуск бота как subprocess"""
        cmd = [sys.executable, "main.py"]
        env = os.environ.copy()

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        # Читаем вывод бота
        async def read_stream(stream, prefix):
            while True:
                line = await stream.readline()
                if not line:
                    break
                try:
                    logger.info(f"[{prefix}] {line.decode('utf-8', errors='replace').strip()}")
                except Exception:
                    pass

        asyncio.create_task(read_stream(self.process.stdout, "BOT"))
        asyncio.create_task(read_stream(self.process.stderr, "ERR"))

        # Ждём завершения
        return await self.process.wait()

    async def start(self):
        """Основной цикл"""
        # Настройка логирования
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler("process_manager.log", encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )

        logger.info("=" * 60)
        logger.info("  Cafe Bot Process Manager")
        logger.info(f"  Python: {sys.version}")
        logger.info(f"  PID: {os.getpid()}")
        logger.info("=" * 60)

        # Запуск фонового бэкапа
        self.backup_task = asyncio.create_task(self._backup_database())
        logger.info(f"[BACKUP] Автобэкап каждые {BACKUP_INTERVAL // 60} минут")

        # Обработка сигналов
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: setattr(self, 'running', False))

        # Главный цикл
        while self.running:
            if not self._should_restart():
                logger.critical(
                    f"Превышен лимит рестартов ({MAX_RESTARTS} за {RESTART_WINDOW}с). "
                    f"Остановка."
                )
                break

            try:
                logger.info(f"[START] Запуск бота... (попытка {len(self.restarts) + 1})")
                exit_code = await self._run_bot()

                if exit_code == 0:
                    logger.info("[STOP] Бот завершён штатно (exit code 0)")
                    break
                else:
                    logger.warning(f"[CRASH] Бот упал с кодом {exit_code}")
                    self._record_restart()

            except FileNotFoundError:
                logger.error("[ERROR] Файл main.py не найден!")
                break
            except Exception as e:
                logger.error(f"[ERROR] Неожиданная ошибка: {e}", exc_info=True)
                self._record_restart()

            if self.running:
                logger.info(f"[RESTART] Перезапуск через {RESTART_DELAY}с...")
                await asyncio.sleep(RESTART_DELAY)

        # Остановка
        logger.info("[STOP] Process Manager остановлен")
        if self.process and self.process.returncode is None:
            try:
                self.process.kill()
            except ProcessLookupError:
                pass

        self.running = False
        if self.backup_task:
            self.backup_task.cancel()


if __name__ == "__main__":
    manager = ProcessManager()
    asyncio.run(manager.start())
