"""Репозитории на SQLAlchemy: перевод между ORM-строками и доменными сущностями."""

from datetime import date, datetime, tzinfo

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from barber_bot.domain.availability import grid_cells
from barber_bot.domain.entities import (
    Appointment,
    AppointmentStatus,
    CancelledBy,
    Client,
    Service,
)
from barber_bot.domain.errors import WindowTakenError
from barber_bot.domain.rules import BookingRules
from barber_bot.domain.schedule import ScheduleException, WeeklySchedule, WorkingHours
from barber_bot.infrastructure.db.models import (
    AppointmentRow,
    ClientRow,
    DailySummaryRow,
    OccupiedCellRow,
    ScheduleExceptionRow,
    ServiceRow,
    WeeklyScheduleRow,
)


class SqlClientRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, client_id: int) -> Client | None:
        row = await self._s.get(ClientRow, client_id)
        return _client(row) if row else None

    async def by_phone(self, phone: str) -> Client | None:
        row = await self._s.scalar(select(ClientRow).where(ClientRow.phone == phone))
        return _client(row) if row else None

    async def by_telegram_id(self, telegram_id: int) -> Client | None:
        row = await self._s.scalar(select(ClientRow).where(ClientRow.telegram_id == telegram_id))
        return _client(row) if row else None

    async def add(self, client: Client) -> Client:
        row = ClientRow(name=client.name, phone=client.phone, telegram_id=client.telegram_id)
        self._s.add(row)
        await self._s.flush()
        client.id = row.id
        return client

    async def update(self, client: Client) -> None:
        await self._s.execute(
            update(ClientRow)
            .where(ClientRow.id == client.id)
            .values(name=client.name, phone=client.phone, telegram_id=client.telegram_id)
        )

    async def delete(self, client_id: int) -> None:
        await self._s.execute(delete(ClientRow).where(ClientRow.id == client_id))


class SqlServiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, service_id: int) -> Service | None:
        row = await self._s.get(ServiceRow, service_id)
        return _service(row) if row else None

    async def list(self, *, include_hidden: bool = False) -> list[Service]:
        query = select(ServiceRow).order_by(ServiceRow.id)
        if not include_hidden:
            query = query.where(ServiceRow.is_hidden.is_(False))
        return [_service(r) for r in await self._s.scalars(query)]

    async def add(self, service: Service) -> Service:
        row = ServiceRow(
            name=service.name,
            duration_minutes=service.duration_minutes,
            price=service.price,
            is_hidden=service.is_hidden,
        )
        self._s.add(row)
        await self._s.flush()
        service.id = row.id
        return service

    async def update(self, service: Service) -> None:
        await self._s.execute(
            update(ServiceRow)
            .where(ServiceRow.id == service.id)
            .values(
                name=service.name,
                duration_minutes=service.duration_minutes,
                price=service.price,
                is_hidden=service.is_hidden,
            )
        )


class SqlAppointmentRepository:
    def __init__(self, session: AsyncSession, tz: tzinfo, rules: BookingRules) -> None:
        self._s = session
        self._tz = tz
        self._rules = rules

    async def get(self, appointment_id: int) -> Appointment | None:
        row = await self._s.get(AppointmentRow, appointment_id)
        return self._appointment(row) if row else None

    async def add(self, appointment: Appointment) -> Appointment:
        row = AppointmentRow()
        _fill(row, appointment)
        self._s.add(row)
        await self._s.flush()
        appointment.id = row.id
        await self._occupy(appointment)
        return appointment

    async def update(self, appointment: Appointment) -> None:
        row = await self._s.get(AppointmentRow, appointment.id)
        if row is None:
            raise LookupError(appointment.id)
        _fill(row, appointment)
        await self._s.execute(
            delete(OccupiedCellRow).where(OccupiedCellRow.appointment_id == appointment.id)
        )
        await self._s.flush()
        if appointment.is_active:
            await self._occupy(appointment)

    async def active_between(self, start: datetime, end: datetime) -> list[Appointment]:
        # У активной записи есть шаги сетки, у отменённой — нет, поэтому ищем по шагам.
        ids = (
            select(OccupiedCellRow.appointment_id)
            .where(OccupiedCellRow.cell_start >= start, OccupiedCellRow.cell_start < end)
            .distinct()
        )
        # Запись, начавшаяся до start, но ещё идущая, попадает сюда через свои поздние шаги.
        query = (
            select(AppointmentRow)
            .where(AppointmentRow.id.in_(ids))
            .order_by(AppointmentRow.starts_at)
        )
        return [self._appointment(r) for r in await self._s.scalars(query)]

    async def upcoming_for_client(self, client_id: int, now: datetime) -> list[Appointment]:
        query = (
            select(AppointmentRow)
            .where(
                AppointmentRow.client_id == client_id,
                AppointmentRow.status == AppointmentStatus.ACTIVE.value,
                AppointmentRow.starts_at > now,
            )
            .order_by(AppointmentRow.starts_at)
        )
        return [self._appointment(r) for r in await self._s.scalars(query)]

    async def due_reminders(self, now: datetime) -> list[Appointment]:
        query = (
            select(AppointmentRow)
            .where(
                AppointmentRow.status == AppointmentStatus.ACTIVE.value,
                AppointmentRow.reminder_sent.is_(False),
                AppointmentRow.remind_at <= now,
                AppointmentRow.starts_at > now,
            )
            .order_by(AppointmentRow.starts_at)
        )
        return [self._appointment(r) for r in await self._s.scalars(query)]

    async def reassign_client(self, from_client_id: int, to_client_id: int) -> None:
        await self._s.execute(
            update(AppointmentRow)
            .where(AppointmentRow.client_id == from_client_id)
            .values(client_id=to_client_id)
        )

    async def _occupy(self, appointment: Appointment) -> None:
        cells = grid_cells(appointment.starts_at, appointment.duration, self._rules)
        self._s.add_all(OccupiedCellRow(cell_start=c, appointment_id=appointment.id) for c in cells)
        try:
            await self._s.flush()
        except IntegrityError as e:
            raise WindowTakenError from e

    def _appointment(self, row: AppointmentRow) -> Appointment:
        return Appointment(
            id=row.id,
            client_id=row.client_id,
            service_id=row.service_id,
            starts_at=row.starts_at.astimezone(self._tz),
            duration_minutes=row.duration_minutes,
            price=row.price,
            is_manual=row.is_manual,
            status=AppointmentStatus(row.status),
            cancelled_by=CancelledBy(row.cancelled_by) if row.cancelled_by else None,
            cancel_reason=row.cancel_reason,
            visit_confirmed=row.visit_confirmed,
            no_show=row.no_show,
            remind_at=row.remind_at.astimezone(self._tz) if row.remind_at else None,
            reminder_sent=row.reminder_sent,
        )


class SqlScheduleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_weekly(self) -> WeeklySchedule:
        rows = await self._s.scalars(select(WeeklyScheduleRow))
        return WeeklySchedule({r.weekday: WorkingHours(r.start, r.end) for r in rows})

    async def set_weekly(self, schedule: WeeklySchedule) -> None:
        await self._s.execute(delete(WeeklyScheduleRow))
        self._s.add_all(
            WeeklyScheduleRow(weekday=d, start=h.start, end=h.end) for d, h in schedule.days.items()
        )
        await self._s.flush()

    async def exceptions_between(self, date_from: date, date_to: date) -> list[ScheduleException]:
        query = (
            select(ScheduleExceptionRow)
            .where(
                ScheduleExceptionRow.date_from <= date_to,
                ScheduleExceptionRow.date_to >= date_from,
            )
            .order_by(ScheduleExceptionRow.id)
        )
        return [_exception(r) for r in await self._s.scalars(query)]

    async def get_exception(self, exception_id: int) -> ScheduleException | None:
        row = await self._s.get(ScheduleExceptionRow, exception_id)
        return _exception(row) if row else None

    async def add_exception(self, exception: ScheduleException) -> ScheduleException:
        row = ScheduleExceptionRow(
            date_from=exception.date_from,
            date_to=exception.date_to,
            start=exception.hours.start if exception.hours else None,
            end=exception.hours.end if exception.hours else None,
        )
        self._s.add(row)
        await self._s.flush()
        return _exception(row)

    async def delete_exception(self, exception_id: int) -> None:
        await self._s.execute(
            delete(ScheduleExceptionRow).where(ScheduleExceptionRow.id == exception_id)
        )


class SqlSummaryLog:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def was_sent(self, day: date) -> bool:
        return await self._s.get(DailySummaryRow, day) is not None

    async def mark_sent(self, day: date, at: datetime) -> None:
        self._s.add(DailySummaryRow(day=day, sent_at=at))
        await self._s.flush()


def _client(row: ClientRow) -> Client:
    return Client(id=row.id, name=row.name, phone=row.phone, telegram_id=row.telegram_id)


def _service(row: ServiceRow) -> Service:
    return Service(
        id=row.id,
        name=row.name,
        duration_minutes=row.duration_minutes,
        price=row.price,
        is_hidden=row.is_hidden,
    )


def _exception(row: ScheduleExceptionRow) -> ScheduleException:
    hours = WorkingHours(row.start, row.end) if row.start and row.end else None
    return ScheduleException(row.date_from, row.date_to, hours, id=row.id)


def _fill(row: AppointmentRow, a: Appointment) -> None:
    row.client_id = a.client_id
    row.service_id = a.service_id
    row.starts_at = a.starts_at
    row.duration_minutes = a.duration_minutes
    row.price = a.price
    row.is_manual = a.is_manual
    row.status = a.status.value
    row.cancelled_by = a.cancelled_by.value if a.cancelled_by else None
    row.cancel_reason = a.cancel_reason
    row.visit_confirmed = a.visit_confirmed
    row.no_show = a.no_show
    row.remind_at = a.remind_at
    row.reminder_sent = a.reminder_sent
