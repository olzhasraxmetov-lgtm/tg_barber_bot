"""Порты — интерфейсы, через которые use cases говорят с внешним миром."""

from collections.abc import Callable
from datetime import date, datetime
from types import TracebackType
from typing import Protocol, Self

from barber_bot.application.notifications import Notification
from barber_bot.domain.entities import Appointment, Client, Service
from barber_bot.domain.schedule import ScheduleException, WeeklySchedule


class Clock(Protocol):
    def now(self) -> datetime:
        """Текущее время — aware datetime в часовом поясе мастера."""
        ...


class Notifier(Protocol):
    async def send(self, notification: Notification) -> None: ...


class ClientRepository(Protocol):
    async def get(self, client_id: int) -> Client | None: ...
    async def by_phone(self, phone: str) -> Client | None: ...
    async def by_telegram_id(self, telegram_id: int) -> Client | None: ...
    async def add(self, client: Client) -> Client: ...
    async def update(self, client: Client) -> None: ...
    async def delete(self, client_id: int) -> None: ...


class ServiceRepository(Protocol):
    async def get(self, service_id: int) -> Service | None: ...
    async def list(self, *, include_hidden: bool = False) -> list[Service]: ...
    async def add(self, service: Service) -> Service: ...
    async def update(self, service: Service) -> None: ...


class AppointmentRepository(Protocol):
    async def get(self, appointment_id: int) -> Appointment | None: ...

    async def add(self, appointment: Appointment) -> Appointment:
        """Сохраняет запись и занимает её шаги сетки. Окно занято → WindowTakenError."""
        ...

    async def update(self, appointment: Appointment) -> None:
        """Сохраняет изменения; шаги сетки синхронизируются со временем и статусом записи.

        Конфликт шагов при переносе → WindowTakenError.
        """
        ...

    async def active_between(self, start: datetime, end: datetime) -> list[Appointment]:
        """Активные записи, пересекающие интервал [start, end)."""
        ...

    async def upcoming_for_client(self, client_id: int, now: datetime) -> list[Appointment]:
        """Активные записи клиента, которые ещё не начались, по времени."""
        ...

    async def due_reminders(self, now: datetime) -> list[Appointment]:
        """Активные, ещё не начавшиеся записи с наступившим и не отправленным напоминанием."""
        ...

    async def reassign_client(self, from_client_id: int, to_client_id: int) -> None:
        """Переносит все записи одного клиента на другого (склейка профилей)."""
        ...


class ScheduleRepository(Protocol):
    async def get_weekly(self) -> WeeklySchedule: ...
    async def set_weekly(self, schedule: WeeklySchedule) -> None: ...
    async def exceptions_between(self, date_from: date, date_to: date) -> list[ScheduleException]:
        """Исключения, пересекающие период, в порядке создания."""
        ...

    async def add_exception(self, exception: ScheduleException) -> ScheduleException: ...
    async def delete_exception(self, exception_id: int) -> None: ...


class SummaryLog(Protocol):
    async def was_sent(self, day: date) -> bool: ...
    async def mark_sent(self, day: date, at: datetime) -> None: ...


class UnitOfWork(Protocol):
    clients: ClientRepository
    services: ServiceRepository
    appointments: AppointmentRepository
    schedule: ScheduleRepository
    summaries: SummaryLog

    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Без commit() изменения откатываются."""
        ...

    async def commit(self) -> None: ...


UnitOfWorkFactory = Callable[[], UnitOfWork]
