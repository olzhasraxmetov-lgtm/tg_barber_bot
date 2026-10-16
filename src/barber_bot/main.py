"""Точка входа: собрать приложение, запустить фоновые задачи и long polling."""

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from barber_bot.application.jobs import BackgroundJobs
from barber_bot.bootstrap import application
from barber_bot.domain.rules import DEFAULT_RULES
from barber_bot.infrastructure.config import Settings
from barber_bot.infrastructure.telegram_notifier import NotificationRenderer, TelegramNotifier
from barber_bot.presentation.texts import Formatter
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
    bot = Bot(
        settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    renderer = NotificationRenderer(
        master_telegram_id=settings.master_telegram_id,
        fmt=Formatter(settings.tz, settings.currency),
        rules=DEFAULT_RULES,
    )
    async with bot, application(settings, TelegramNotifier(bot, renderer)) as app:
        if settings.seed_demo and await seed_demo(app.master):
            logger.info("База пустая — добавлены демо-услуги и график")
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
