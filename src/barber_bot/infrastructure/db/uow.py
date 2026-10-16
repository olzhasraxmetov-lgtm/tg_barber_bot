from datetime import tzinfo
from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from barber_bot.application.ports import (
    AppointmentRepository,
    ClientRepository,
    ScheduleRepository,
    ServiceRepository,
    SummaryLog,
)
from barber_bot.domain.rules import BookingRules
from barber_bot.infrastructure.db.repositories import (
    SqlAppointmentRepository,
    SqlClientRepository,
    SqlScheduleRepository,
    SqlServiceRepository,
    SqlSummaryLog,
)


class SqlUnitOfWork:
    """Одна транзакция на один вызов use case. Без commit() всё откатывается."""

    # Типы портов, а не реализаций: атрибуты протокола UnitOfWork изменяемые, а значит
    # инвариантные — иначе SqlUnitOfWork формально ему не соответствует.
    clients: ClientRepository
    services: ServiceRepository
    appointments: AppointmentRepository
    schedule: ScheduleRepository
    summaries: SummaryLog

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], tz: tzinfo, rules: BookingRules
    ) -> None:
        self._session_factory = session_factory
        self._tz = tz
        self._rules = rules

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.clients = SqlClientRepository(self._session)
        self.services = SqlServiceRepository(self._session)
        self.appointments = SqlAppointmentRepository(self._session, self._tz, self._rules)
        self.schedule = SqlScheduleRepository(self._session)
        self.summaries = SqlSummaryLog(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            await self._session.rollback()
        finally:
            await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()
