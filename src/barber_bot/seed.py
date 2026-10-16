"""Демо-данные: услуги и график, чтобы в свежем боте сразу можно было записаться."""

import asyncio
import logging
from datetime import time

from barber_bot.application.master_actions import MasterActions
from barber_bot.bootstrap import application
from barber_bot.domain.schedule import WeeklySchedule, WorkingHours
from barber_bot.infrastructure.config import Settings
from barber_bot.infrastructure.logging_notifier import LoggingNotifier

logger = logging.getLogger(__name__)

DEMO_SERVICES = [
    ("Мужская стрижка", 60, 6000),
    ("Оформление бороды", 30, 3500),
    ("Стрижка + борода", 90, 9000),
]
WEEKDAYS = WorkingHours(time(10), time(20))
SATURDAY = WorkingHours(time(11), time(18))
DEMO_SCHEDULE = WeeklySchedule({**dict.fromkeys(range(5), WEEKDAYS), 5: SATURDAY})


async def seed_demo(master: MasterActions) -> bool:
    """Заполняет только свежую базу — без единой услуги, даже скрытой. True — данные добавлены.

    Признак «свежести» — услуги, а не график: мастер вправе сделать все дни выходными,
    и перезапуск не должен вернуть ему демо-график.
    """
    if await master.list_services():
        return False
    for name, minutes, price in DEMO_SERVICES:
        await master.add_service(name, minutes, price)
    if not (await master.get_weekly_schedule()).days:
        await master.set_weekly_schedule(DEMO_SCHEDULE)
    return True


async def _main() -> None:
    settings = Settings()  # type: ignore[call-arg]  # обязательные поля приходят из .env
    async with application(settings, LoggingNotifier()) as app:
        added = await seed_demo(app.master)
    logger.info("Демо-данные добавлены" if added else "База не пустая — seed пропущен")


def run() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    asyncio.run(_main())
