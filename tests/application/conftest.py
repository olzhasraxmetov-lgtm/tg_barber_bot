"""Фикстуры уровня use cases: настоящий SQLite, поднятый миграциями Alembic."""

from collections.abc import AsyncIterator
from datetime import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from support import CLIENT_TG, NOW, TZ, App, FakeClock, RecordingNotifier

from barber_bot.application.client_actions import ClientActions
from barber_bot.application.context import AppContext
from barber_bot.application.jobs import BackgroundJobs
from barber_bot.application.master_actions import MasterActions
from barber_bot.domain.rules import DEFAULT_RULES
from barber_bot.domain.schedule import WeeklySchedule, WorkingHours
from barber_bot.infrastructure.db.engine import create_engine, create_session_factory
from barber_bot.infrastructure.db.uow import SqlUnitOfWork

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    return url


@pytest.fixture
async def app(db_url: str) -> AsyncIterator[App]:
    engine = create_engine(db_url)
    sessions = create_session_factory(engine)
    clock = FakeClock(NOW)
    notifier = RecordingNotifier()
    ctx = AppContext(
        uow=lambda: SqlUnitOfWork(sessions, TZ, DEFAULT_RULES),
        clock=clock,
        notifier=notifier,
        tz=TZ,
        rules=DEFAULT_RULES,
    )
    master = MasterActions(ctx)
    await master.set_weekly_schedule(
        WeeklySchedule({d: WorkingHours(time(10), time(20)) for d in range(5)})
    )
    haircut = await master.add_service("Стрижка", 60, 5000)
    beard = await master.add_service("Борода", 30, 3000)
    combo = await master.add_service("Стрижка + борода", 90, 7000)
    yield App(
        ctx, clock, notifier, ClientActions(ctx), master, BackgroundJobs(ctx), haircut, beard, combo
    )
    await engine.dispose()


@pytest.fixture
async def registered(app: App) -> App:
    await app.client.register(CLIENT_TG, "Алексей", "+7 701 111 11 11")
    return app
