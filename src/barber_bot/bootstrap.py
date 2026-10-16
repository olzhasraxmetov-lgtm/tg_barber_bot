"""Сборка приложения из настроек: база, часы, use cases. Общая для бота и seed-скрипта."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from barber_bot.application.client_actions import ClientActions
from barber_bot.application.context import AppContext
from barber_bot.application.jobs import BackgroundJobs
from barber_bot.application.master_actions import MasterActions
from barber_bot.application.ports import Notifier
from barber_bot.domain.rules import DEFAULT_RULES
from barber_bot.infrastructure.clock import SystemClock
from barber_bot.infrastructure.config import Settings
from barber_bot.infrastructure.db.engine import create_engine, create_session_factory
from barber_bot.infrastructure.db.migrate import upgrade_to_head
from barber_bot.infrastructure.db.uow import SqlUnitOfWork


@dataclass(frozen=True, slots=True)
class Container:
    settings: Settings
    ctx: AppContext
    client: ClientActions
    master: MasterActions
    jobs: BackgroundJobs


@asynccontextmanager
async def application(settings: Settings, notifier: Notifier) -> AsyncIterator[Container]:
    """Приводит схему базы к последней миграции и собирает use cases поверх неё."""
    upgrade_to_head(settings.database_url)
    engine = create_engine(settings.database_url)
    sessions = create_session_factory(engine)
    tz = settings.tz
    rules = DEFAULT_RULES
    ctx = AppContext(
        uow=lambda: SqlUnitOfWork(sessions, tz, rules),
        clock=SystemClock(tz),
        notifier=notifier,
        tz=tz,
        rules=rules,
        phone_country_code=settings.phone_country_code,
    )
    try:
        yield Container(settings, ctx, ClientActions(ctx), MasterActions(ctx), BackgroundJobs(ctx))
    finally:
        await engine.dispose()
