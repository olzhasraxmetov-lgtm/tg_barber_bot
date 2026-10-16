"""Запуск: демо-данные для свежей базы и живучесть фонового цикла."""

import asyncio
from collections.abc import AsyncIterator
from datetime import time

import pytest
from support import NOW, TZ, App, FakeClock, RecordingNotifier

from barber_bot.application.context import AppContext
from barber_bot.application.jobs import BackgroundJobs
from barber_bot.application.master_actions import MasterActions
from barber_bot.domain.rules import DEFAULT_RULES
from barber_bot.domain.schedule import WeeklySchedule, WorkingHours
from barber_bot.infrastructure.db.engine import create_engine, create_session_factory
from barber_bot.infrastructure.db.uow import SqlUnitOfWork
from barber_bot.main import run_jobs_forever
from barber_bot.seed import DEMO_SCHEDULE, DEMO_SERVICES, seed_demo


@pytest.fixture
async def empty_master(db_url: str) -> AsyncIterator[MasterActions]:
    engine = create_engine(db_url)
    sessions = create_session_factory(engine)
    ctx = AppContext(
        uow=lambda: SqlUnitOfWork(sessions, TZ, DEFAULT_RULES),
        clock=FakeClock(NOW),
        notifier=RecordingNotifier(),
        tz=TZ,
        rules=DEFAULT_RULES,
    )
    yield MasterActions(ctx)
    await engine.dispose()


async def test_seed_fills_fresh_database_once(empty_master: MasterActions) -> None:
    assert await seed_demo(empty_master)
    assert not await seed_demo(empty_master)

    services = await empty_master.list_services()
    assert [(s.name, s.duration_minutes, s.price) for s in services] == DEMO_SERVICES
    assert await empty_master.get_weekly_schedule() == DEMO_SCHEDULE


async def test_seed_keeps_masters_data(app: App) -> None:
    before = await app.master.list_services()
    assert not await seed_demo(app.master)
    assert await app.master.list_services() == before


async def test_seed_does_not_restore_schedule_after_master_closed_all_days(
    empty_master: MasterActions,
) -> None:
    await seed_demo(empty_master)
    await empty_master.set_weekly_schedule(WeeklySchedule())
    assert not await seed_demo(empty_master)
    assert (await empty_master.get_weekly_schedule()).days == {}


def test_demo_schedule_matches_spec() -> None:
    assert DEMO_SCHEDULE.hours_on(0) == WorkingHours(time(10), time(20))
    assert DEMO_SCHEDULE.hours_on(5) == WorkingHours(time(11), time(18))
    assert DEMO_SCHEDULE.hours_on(6) is None


class FlakyJobs(BackgroundJobs):
    def __init__(self) -> None:
        self.calls = 0

    async def send_due_reminders(self) -> int:
        self.calls += 1
        raise RuntimeError("база недоступна")

    async def send_daily_summary(self) -> bool:
        raise RuntimeError("и это тоже")


async def test_jobs_loop_survives_failures() -> None:
    jobs = FlakyJobs()
    task = asyncio.create_task(run_jobs_forever(jobs, interval=0))
    while jobs.calls < 3:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
