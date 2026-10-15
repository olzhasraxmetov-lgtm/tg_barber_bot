import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from barber_bot.application.notifications import AppointmentDetails, Notification
from barber_bot.application.ports import Clock, Notifier, UnitOfWork, UnitOfWorkFactory
from barber_bot.domain.availability import Interval, free_windows, horizon_dates
from barber_bot.domain.entities import Appointment
from barber_bot.domain.errors import NotFoundError
from barber_bot.domain.rules import BookingRules
from barber_bot.domain.schedule import ScheduleException, WeeklySchedule, working_hours_on

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AppContext:
    """Всё, что нужно use cases: собирается один раз в точке входа."""

    uow: UnitOfWorkFactory
    clock: Clock
    notifier: Notifier
    tz: tzinfo
    rules: BookingRules

    def day_bounds(self, day: date) -> tuple[datetime, datetime]:
        start = datetime.combine(day, time.min, tzinfo=self.tz)
        return start, start + timedelta(days=1)

    async def notify(self, notification: Notification) -> None:
        """Уведомление не должно ломать уже закоммиченное действие — ошибки только логируем."""
        try:
            await self.notifier.send(notification)
        except Exception:
            logger.exception("Не удалось отправить уведомление %r", type(notification).__name__)


async def load_details(uow: UnitOfWork, appointment: Appointment) -> AppointmentDetails:
    client = await uow.clients.get(appointment.client_id)
    service = await uow.services.get(appointment.service_id)
    if client is None or service is None:
        raise NotFoundError
    return AppointmentDetails(appointment, client, service.name)


async def windows_by_day(
    ctx: AppContext,
    uow: UnitOfWork,
    days: list[date],
    duration: timedelta,
    *,
    exclude_appointment_id: int | None = None,
) -> dict[date, list[datetime]]:
    """Свободные окна на несколько дней за три запроса к хранилищу."""
    if not days:
        return {}
    now = ctx.clock.now()
    schedule = await uow.schedule.get_weekly()
    exceptions = await uow.schedule.exceptions_between(days[0], days[-1])
    range_start, _ = ctx.day_bounds(days[0])
    _, range_end = ctx.day_bounds(days[-1])
    busy = [
        Interval(a.starts_at, a.ends_at)
        for a in await uow.appointments.active_between(range_start, range_end)
        if a.id != exclude_appointment_id
    ]
    return {
        day: free_windows(
            day=day,
            duration=duration,
            schedule=schedule,
            exceptions=exceptions,
            busy=busy,
            now=now,
            tz=ctx.tz,
            rules=ctx.rules,
        )
        for day in days
    }


async def available_dates(
    ctx: AppContext,
    uow: UnitOfWork,
    duration: timedelta,
    *,
    exclude_appointment_id: int | None = None,
) -> list[date]:
    days = horizon_dates(ctx.clock.now(), ctx.rules)
    by_day = await windows_by_day(
        ctx, uow, days, duration, exclude_appointment_id=exclude_appointment_id
    )
    return [day for day, windows in by_day.items() if windows]


async def is_free_window(
    ctx: AppContext,
    uow: UnitOfWork,
    starts_at: datetime,
    duration: timedelta,
    *,
    exclude_appointment_id: int | None = None,
) -> bool:
    day = starts_at.astimezone(ctx.tz).date()
    by_day = await windows_by_day(
        ctx, uow, [day], duration, exclude_appointment_id=exclude_appointment_id
    )
    return starts_at in by_day[day]


def fits_working_hours(
    ctx: AppContext,
    appointment: Appointment,
    schedule: WeeklySchedule,
    exceptions: list[ScheduleException],
) -> bool:
    """Помещается ли запись в рабочие часы своего дня при данном графике и исключениях."""
    local_start = appointment.starts_at.astimezone(ctx.tz)
    day = local_start.date()
    hours = working_hours_on(day, schedule, exceptions)
    if hours is None:
        return False
    day_start = datetime.combine(day, hours.start, tzinfo=ctx.tz)
    day_end = datetime.combine(day, hours.end, tzinfo=ctx.tz)
    return day_start <= local_start and appointment.ends_at <= day_end
