"""Точка входа: собрать приложение, запустить фоновые задачи и long polling."""

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher

from barber_bot.application.jobs import BackgroundJobs
from barber_bot.bootstrap import application
from barber_bot.infrastructure.config import Settings
from barber_bot.infrastructure.logging_notifier import LoggingNotifier
from barber_bot.seed import seed_demo

logger = logging.getLogger(__name__)

JOBS_INTERVAL_SECONDS = 60


async def run_jobs_forever(jobs: BackgroundJobs, interval: float = JOBS_INTERVAL_SECONDS) -> None:
    """Раз в интервал — напоминания и сводка дня. Сбой одной итерации не останавливает цикл:
    пропущенное доотправится на следующей, отметки об отправке лежат в базе."""
    while True:
        for job in (jobs.send_due_reminders, jobs.send_daily_summary):
            try:
                await job()
            except Exception:
                logger.exception("Фоновая задача %s упала", job.__name__)
        await asyncio.sleep(interval)


async def main() -> None:
    settings = Settings()  # type: ignore[call-arg]  # обязательные поля приходят из .env
    async with application(settings, LoggingNotifier()) as app:
        if settings.seed_demo and await seed_demo(app.master):
            logger.info("База пустая — добавлены демо-услуги и график")
        bot = Bot(settings.bot_token.get_secret_value())
        dp = Dispatcher()
        dp.workflow_data.update(
            settings=settings, client_actions=app.client, master_actions=app.master
        )
        jobs_task = asyncio.create_task(run_jobs_forever(app.jobs))
        try:
            await dp.start_polling(bot)
        finally:
            jobs_task.cancel()
            with suppress(asyncio.CancelledError):
                await jobs_task


def run() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(main())
