"""Use cases мастера: расписание, отмена, ручная запись, график, исключения, услуги, неявки."""

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

from barber_bot.application.context import (
    AppContext,
    available_dates,
    fits_working_hours,
    is_free_window,
    load_details,
    windows_by_day,
)
from barber_bot.application.notifications import (
    AppointmentDetails,
    BookingConfirmation,
    CancelledByMaster,
)
from barber_bot.application.ports import UnitOfWork
from barber_bot.domain.entities import Appointment, Client, Service, normalize_phone
from barber_bot.domain.errors import NotFoundError, WindowUnavailableError
from barber_bot.domain.schedule import ScheduleException, WeeklySchedule

SCHEDULE_CHANGE_REASON = "Мастер изменил график работы"


@dataclass(frozen=True, slots=True)
class ScheduleChangeResult:
    """Итог изменения графика или исключения.

    applied=False и непустой conflicts — изменение не применено: есть записи, которые в новый
    график не помещаются; повторить с cancel_conflicts=True, чтобы отменить их.
    """

    applied: bool
    conflicts: list[AppointmentDetails] = field(default_factory=list)
    exception: ScheduleException | None = None


class MasterActions:
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    # --- расписание и записи ---

    async def schedule_for(self, day: date) -> list[AppointmentDetails]:
        async with self._ctx.uow() as uow:
            start, end = self._ctx.day_bounds(day)
            return [
                await load_details(uow, a)
                for a in await uow.appointments.active_between(start, end)
            ]

    async def get_appointment(self, appointment_id: int) -> AppointmentDetails:
        async with self._ctx.uow() as uow:
            return await load_details(uow, await _appointment(uow, appointment_id))

    async def cancel(self, appointment_id: int, reason: str | None = None) -> AppointmentDetails:
        async with self._ctx.uow() as uow:
            appointment = await _appointment(uow, appointment_id)
            appointment.cancel_by_master(reason)
            await uow.appointments.update(appointment)
            details = await load_details(uow, appointment)
            await uow.commit()
        await self._notify_cancelled(details)
        return details

    async def set_no_show(self, appointment_id: int, value: bool) -> AppointmentDetails:
        async with self._ctx.uow() as uow:
            appointment = await _appointment(uow, appointment_id)
            appointment.set_no_show(value, self._ctx.clock.now())
            await uow.appointments.update(appointment)
            details = await load_details(uow, appointment)
            await uow.commit()
            return details

    # --- ручная запись ---

    async def available_dates(self, service_id: int) -> list[date]:
        async with self._ctx.uow() as uow:
            service = await _service(uow, service_id)
            return await available_dates(self._ctx, uow, service.duration)

    async def free_windows(self, service_id: int, day: date) -> list[datetime]:
        async with self._ctx.uow() as uow:
            service = await _service(uow, service_id)
            return (await windows_by_day(self._ctx, uow, [day], service.duration))[day]

    async def manual_booking(
        self, name: str, phone: str, service_id: int, starts_at: datetime
    ) -> AppointmentDetails:
        """Ручная запись. Клиент ищется по телефону; если он уже в боте — получит подтверждение."""
        ctx = self._ctx
        phone = normalize_phone(phone)
        async with ctx.uow() as uow:
            service = await _service(uow, service_id)
            if not await is_free_window(ctx, uow, starts_at, service.duration):
                raise WindowUnavailableError
            client = await uow.clients.by_phone(phone)
            if client is None:
                client = await uow.clients.add(Client(name.strip(), phone))
            appointment = await uow.appointments.add(
                Appointment.book(
                    client_id=_client_id(client),
                    service=service,
                    starts_at=starts_at,
                    now=ctx.clock.now(),
                    rules=ctx.rules,
                    is_manual=True,
                )
            )
            await uow.commit()
            details = AppointmentDetails(appointment, client, service.name)
        if client.telegram_id is not None:
            await ctx.notify(BookingConfirmation(client.telegram_id, details))
        return details

    # --- график и исключения ---

    async def get_weekly_schedule(self) -> WeeklySchedule:
        async with self._ctx.uow() as uow:
            return await uow.schedule.get_weekly()

    async def set_weekly_schedule(
        self, schedule: WeeklySchedule, *, cancel_conflicts: bool = False
    ) -> ScheduleChangeResult:
        schedule.validate(self._ctx.rules)
        async with self._ctx.uow() as uow:
            future = await self._future_appointments(uow)
            exceptions = await self._exceptions_for(uow, future)
            conflicts = [
                a for a in future if not fits_working_hours(self._ctx, a, schedule, exceptions)
            ]
            result = await self._resolve(uow, conflicts, cancel_conflicts)
            if result.applied:
                await uow.schedule.set_weekly(schedule)
                await uow.commit()
        await self._notify_all_cancelled(result, cancel_conflicts)
        return result

    async def list_exceptions(self) -> list[ScheduleException]:
        today = self._ctx.clock.now().date()
        async with self._ctx.uow() as uow:
            return await uow.schedule.exceptions_between(today, date.max)

    async def add_exception(
        self, exception: ScheduleException, *, cancel_conflicts: bool = False
    ) -> ScheduleChangeResult:
        exception.validate(self._ctx.rules)
        async with self._ctx.uow() as uow:
            start, _ = self._ctx.day_bounds(exception.date_from)
            _, end = self._ctx.day_bounds(exception.date_to)
            now = self._ctx.clock.now()
            affected = [
                a
                for a in await uow.appointments.active_between(max(start, now), end)
                if a.starts_at >= now
            ]
            schedule = await uow.schedule.get_weekly()
            existing = await uow.schedule.exceptions_between(exception.date_from, exception.date_to)
            conflicts = [
                a
                for a in affected
                if not fits_working_hours(self._ctx, a, schedule, [*existing, exception])
            ]
            result = await self._resolve(uow, conflicts, cancel_conflicts)
            if result.applied:
                saved = await uow.schedule.add_exception(exception)
                await uow.commit()
                result = replace(result, exception=saved)
        await self._notify_all_cancelled(result, cancel_conflicts)
        return result

    async def delete_exception(self, exception_id: int) -> None:
        async with self._ctx.uow() as uow:
            await uow.schedule.delete_exception(exception_id)
            await uow.commit()

    # --- услуги ---

    async def list_services(self) -> list[Service]:
        async with self._ctx.uow() as uow:
            return await uow.services.list(include_hidden=True)

    async def add_service(self, name: str, duration_minutes: int, price: int) -> Service:
        service = Service(name.strip(), duration_minutes, price)
        service.validate(self._ctx.rules)
        async with self._ctx.uow() as uow:
            saved = await uow.services.add(service)
            await uow.commit()
            return saved

    async def update_service(
        self,
        service_id: int,
        *,
        name: str | None = None,
        duration_minutes: int | None = None,
        price: int | None = None,
        is_hidden: bool | None = None,
    ) -> Service:
        """Меняет услугу для будущих записей; у существующих записей длительность и цена прежние."""
        async with self._ctx.uow() as uow:
            service = await _service(uow, service_id)
            if name is not None:
                service.name = name.strip()
            if duration_minutes is not None:
                service.duration_minutes = duration_minutes
            if price is not None:
                service.price = price
            if is_hidden is not None:
                service.is_hidden = is_hidden
            service.validate(self._ctx.rules)
            await uow.services.update(service)
            await uow.commit()
            return service

    # --- внутреннее ---

    async def _future_appointments(self, uow: UnitOfWork) -> list[Appointment]:
        now = self._ctx.clock.now()
        _, end = self._ctx.day_bounds(now.date() + timedelta(days=self._ctx.rules.horizon_days))
        return [a for a in await uow.appointments.active_between(now, end) if a.starts_at >= now]

    async def _exceptions_for(
        self, uow: UnitOfWork, appointments: list[Appointment]
    ) -> list[ScheduleException]:
        if not appointments:
            return []
        days = [a.starts_at.astimezone(self._ctx.tz).date() for a in appointments]
        return await uow.schedule.exceptions_between(min(days), max(days))

    async def _resolve(
        self, uow: UnitOfWork, conflicts: list[Appointment], cancel_conflicts: bool
    ) -> ScheduleChangeResult:
        details = [await load_details(uow, a) for a in conflicts]
        if conflicts and not cancel_conflicts:
            return ScheduleChangeResult(applied=False, conflicts=details)
        for appointment in conflicts:
            appointment.cancel_by_master(SCHEDULE_CHANGE_REASON)
            await uow.appointments.update(appointment)
        return ScheduleChangeResult(applied=True, conflicts=details)

    async def _notify_all_cancelled(self, result: ScheduleChangeResult, cancelled: bool) -> None:
        if result.applied and cancelled:
            for details in result.conflicts:
                await self._notify_cancelled(details)

    async def _notify_cancelled(self, details: AppointmentDetails) -> None:
        if details.client.telegram_id is not None:
            await self._ctx.notify(CancelledByMaster(details.client.telegram_id, details))


async def _appointment(uow: UnitOfWork, appointment_id: int) -> Appointment:
    appointment = await uow.appointments.get(appointment_id)
    if appointment is None:
        raise NotFoundError
    return appointment


async def _service(uow: UnitOfWork, service_id: int) -> Service:
    service = await uow.services.get(service_id)
    if service is None:
        raise NotFoundError
    return service


def _client_id(client: Client) -> int:
    if client.id is None:
        raise ValueError("Клиент ещё не сохранён")
    return client.id
