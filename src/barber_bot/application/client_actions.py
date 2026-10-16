"""Use cases клиента: профиль, запись, мои записи, отмена, перенос, подтверждение визита."""

from datetime import date, datetime

from barber_bot.application.context import (
    AppContext,
    available_dates,
    is_free_window,
    load_details,
    windows_by_day,
)
from barber_bot.application.notifications import (
    AppointmentDetails,
    BookingConfirmation,
    CancelledByClient,
    NewAppointment,
    Rescheduled,
    VisitConfirmed,
)
from barber_bot.application.ports import UnitOfWork
from barber_bot.domain.entities import Appointment, Client, Service, clean_name
from barber_bot.domain.errors import (
    ClientNotRegisteredError,
    NotFoundError,
    PhoneTakenError,
    ServiceHiddenError,
    WindowUnavailableError,
)


class ClientActions:
    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    # --- профиль ---

    async def get_profile(self, telegram_id: int) -> Client | None:
        async with self._ctx.uow() as uow:
            return await uow.clients.by_telegram_id(telegram_id)

    async def register(self, telegram_id: int, name: str, phone: str) -> Client:
        """Создаёт или обновляет профиль. Если телефон уже есть у клиента из ручной записи —
        склеивает профили: его записи становятся записями этого Telegram-аккаунта."""
        phone = self._ctx.normalize_phone(phone)
        name = clean_name(name)
        async with self._ctx.uow() as uow:
            me = await uow.clients.by_telegram_id(telegram_id)
            owner = await uow.clients.by_phone(phone)

            if owner is not None and owner.telegram_id not in (None, telegram_id):
                raise PhoneTakenError
            if owner is not None and me is not None and owner.id != me.id:
                # Сменили телефон в профиле на номер клиента из ручной записи.
                await uow.appointments.reassign_client(_id(owner), _id(me))
                await uow.clients.delete(_id(owner))
                owner = None

            if owner is not None:
                owner.telegram_id = telegram_id
                owner.name = name
                await uow.clients.update(owner)
                client = owner
            elif me is not None:
                me.name, me.phone = name, phone
                await uow.clients.update(me)
                client = me
            else:
                client = await uow.clients.add(Client(name, phone, telegram_id))
            await uow.commit()
            return client

    # --- услуги и окна ---

    async def list_services(self) -> list[Service]:
        async with self._ctx.uow() as uow:
            return await uow.services.list()

    async def available_dates(self, service_id: int) -> list[date]:
        async with self._ctx.uow() as uow:
            service = await _visible_service(uow, service_id)
            return await available_dates(self._ctx, uow, service.duration)

    async def free_windows(self, service_id: int, day: date) -> list[datetime]:
        async with self._ctx.uow() as uow:
            service = await _visible_service(uow, service_id)
            return (await windows_by_day(self._ctx, uow, [day], service.duration))[day]

    async def reschedule_dates(self, telegram_id: int, appointment_id: int) -> list[date]:
        """Даты для переноса: считаются по длительности записи, своя запись окна не занимает."""
        async with self._ctx.uow() as uow:
            appointment = await _own_appointment(uow, telegram_id, appointment_id)
            return await available_dates(
                self._ctx, uow, appointment.duration, exclude_appointment_id=appointment_id
            )

    async def reschedule_windows(
        self, telegram_id: int, appointment_id: int, day: date
    ) -> list[datetime]:
        async with self._ctx.uow() as uow:
            appointment = await _own_appointment(uow, telegram_id, appointment_id)
            by_day = await windows_by_day(
                self._ctx, uow, [day], appointment.duration, exclude_appointment_id=appointment_id
            )
            return by_day[day]

    # --- запись ---

    async def book(
        self, telegram_id: int, service_id: int, starts_at: datetime
    ) -> AppointmentDetails:
        ctx = self._ctx
        async with ctx.uow() as uow:
            client = await _registered(uow, telegram_id)
            service = await _visible_service(uow, service_id)
            if not await is_free_window(ctx, uow, starts_at, service.duration):
                raise WindowUnavailableError
            appointment = await uow.appointments.add(
                Appointment.book(
                    client_id=_id(client),
                    service=service,
                    starts_at=starts_at,
                    now=ctx.clock.now(),
                    rules=ctx.rules,
                )
            )
            await uow.commit()
            details = AppointmentDetails(appointment, client, service.name)
        await ctx.notify(NewAppointment(details))
        await ctx.notify(BookingConfirmation(telegram_id, details))
        return details

    async def my_appointments(self, telegram_id: int) -> list[AppointmentDetails]:
        async with self._ctx.uow() as uow:
            client = await _registered(uow, telegram_id)
            appointments = await uow.appointments.upcoming_for_client(
                _id(client), self._ctx.clock.now()
            )
            return [await load_details(uow, a) for a in appointments]

    async def get_appointment(self, telegram_id: int, appointment_id: int) -> AppointmentDetails:
        async with self._ctx.uow() as uow:
            appointment = await _own_appointment(uow, telegram_id, appointment_id)
            return await load_details(uow, appointment)

    async def can_change(self, telegram_id: int, appointment_id: int) -> bool:
        """Можно ли клиенту самому отменить или перенести запись прямо сейчас."""
        async with self._ctx.uow() as uow:
            appointment = await _own_appointment(uow, telegram_id, appointment_id)
            return appointment.client_can_change(self._ctx.clock.now(), self._ctx.rules)

    async def cancel(self, telegram_id: int, appointment_id: int) -> AppointmentDetails:
        ctx = self._ctx
        async with ctx.uow() as uow:
            appointment = await _own_appointment(uow, telegram_id, appointment_id)
            appointment.cancel_by_client(ctx.clock.now(), ctx.rules)
            await uow.appointments.update(appointment)
            details = await load_details(uow, appointment)
            await uow.commit()
        await ctx.notify(CancelledByClient(details))
        return details

    async def reschedule(
        self, telegram_id: int, appointment_id: int, new_start: datetime
    ) -> AppointmentDetails:
        ctx = self._ctx
        async with ctx.uow() as uow:
            appointment = await _own_appointment(uow, telegram_id, appointment_id)
            old_start = appointment.starts_at
            # Сначала правило «не позже чем за 3 часа», потом окно — так клиент получит
            # «свяжитесь с мастером», а не «окно занято», когда переносить уже поздно.
            appointment.ensure_client_can_change(ctx.clock.now(), ctx.rules)
            if not await is_free_window(
                ctx, uow, new_start, appointment.duration, exclude_appointment_id=appointment_id
            ):
                raise WindowUnavailableError
            appointment.reschedule(new_start, ctx.clock.now(), ctx.rules)
            await uow.appointments.update(appointment)
            details = await load_details(uow, appointment)
            await uow.commit()
        await ctx.notify(Rescheduled(details, old_start))
        return details

    async def confirm_visit(self, telegram_id: int, appointment_id: int) -> AppointmentDetails:
        ctx = self._ctx
        async with ctx.uow() as uow:
            appointment = await _own_appointment(uow, telegram_id, appointment_id)
            already = appointment.visit_confirmed
            appointment.confirm_visit()
            await uow.appointments.update(appointment)
            details = await load_details(uow, appointment)
            await uow.commit()
        if not already:
            await ctx.notify(VisitConfirmed(details))
        return details


async def _registered(uow: UnitOfWork, telegram_id: int) -> Client:
    client = await uow.clients.by_telegram_id(telegram_id)
    if client is None:
        raise ClientNotRegisteredError
    return client


async def _visible_service(uow: UnitOfWork, service_id: int) -> Service:
    service = await uow.services.get(service_id)
    if service is None:
        raise NotFoundError
    if service.is_hidden:
        raise ServiceHiddenError
    return service


async def _own_appointment(uow: UnitOfWork, telegram_id: int, appointment_id: int) -> Appointment:
    client = await _registered(uow, telegram_id)
    appointment = await uow.appointments.get(appointment_id)
    if appointment is None or appointment.client_id != client.id:
        raise NotFoundError
    return appointment


def _id(entity: Client) -> int:
    if entity.id is None:
        raise ValueError("Клиент ещё не сохранён")
    return entity.id
