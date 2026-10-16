"""Запись и перенос: услуга → дата → свободное окно → подтверждение.

Перенос — тот же диалог с `appointment_id` в start_data: начинается с даты, а окна
считаются по длительности самой записи (своё время она не занимает).
"""

from datetime import date, datetime, time
from typing import Any

from aiogram.types import CallbackQuery
from aiogram_dialog import ChatEvent, Dialog, DialogManager, ShowMode, StartMode, Window
from aiogram_dialog.widgets.kbd import (
    Button,
    Cancel,
    Column,
    Group,
    ManagedCalendar,
    Select,
    SwitchTo,
)
from aiogram_dialog.widgets.text import Const, Format

from barber_bot.application.client_actions import ClientActions
from barber_bot.domain.errors import (
    NotFoundError,
    TooLateToChangeError,
    WindowTakenError,
    WindowUnavailableError,
)
from barber_bot.domain.rules import BookingRules
from barber_bot.presentation import flash, texts
from barber_bot.presentation.client.states import Booking, ClientMenu
from barber_bot.presentation.deps import client_actions, clock, formatter, rules, user_id
from barber_bot.presentation.texts import Formatter
from barber_bot.presentation.widgets import CALENDAR_DATES, AvailableDatesCalendar

APPOINTMENT_ID = "appointment_id"
SERVICE_ID = "service_id"
DAY = "day"
START = "start"


def _rescheduling(manager: DialogManager) -> int | None:
    value = manager.dialog_data.get(APPOINTMENT_ID)
    return int(value) if value is not None else None


def _day(manager: DialogManager) -> date:
    return date.fromisoformat(manager.dialog_data[DAY])


async def _subject(manager: DialogManager, actions: ClientActions) -> tuple[str, int, int]:
    """Что записываем: (название услуги, длительность в минутах, цена)."""
    appointment_id = _rescheduling(manager)
    if appointment_id is not None:
        details = await actions.get_appointment(user_id(manager), appointment_id)
        a = details.appointment
        return details.service_name, a.duration_minutes, a.price
    service_id = manager.dialog_data[SERVICE_ID]
    for service in await actions.list_services():
        if service.id == service_id:
            return service.name, service.duration_minutes, service.price
    raise NotFoundError


async def _windows(manager: DialogManager, actions: ClientActions, day: date) -> list[datetime]:
    appointment_id = _rescheduling(manager)
    if appointment_id is not None:
        return await actions.reschedule_windows(user_id(manager), appointment_id, day)
    return await actions.free_windows(manager.dialog_data[SERVICE_ID], day)


# --- услуга ---


async def services_getter(
    client_actions: ClientActions, fmt: Formatter, **_: Any
) -> dict[str, Any]:
    services = await client_actions.list_services()
    return {
        "text": texts.CHOOSE_SERVICE if services else texts.NO_SERVICES,
        "services": [(s.id, texts.service_line(s, fmt)) for s in services],
    }


async def on_service_selected(
    _: CallbackQuery, __: Any, manager: DialogManager, service_id: int
) -> None:
    manager.dialog_data[SERVICE_ID] = service_id
    await manager.switch_to(Booking.date)


# --- дата ---


async def date_getter(
    dialog_manager: DialogManager,
    client_actions: ClientActions,
    rules: BookingRules,
    **_: Any,
) -> dict[str, Any]:
    name, _duration, _price = await _subject(dialog_manager, client_actions)
    appointment_id = _rescheduling(dialog_manager)
    if appointment_id is not None:
        dates = await client_actions.reschedule_dates(user_id(dialog_manager), appointment_id)
    else:
        dates = await client_actions.available_dates(dialog_manager.dialog_data[SERVICE_ID])
    header = texts.header_for(name)
    template = texts.CHOOSE_DATE if dates else texts.NO_DATES
    return {
        "text": template.format(header=header, days=rules.horizon_days),
        CALENDAR_DATES: dates,
        "has_dates": bool(dates),
        "is_reschedule": appointment_id is not None,
    }


async def on_date_selected(
    event: ChatEvent, _: ManagedCalendar, manager: DialogManager, day: date, /
) -> None:
    # Недоступные дни в календаре тоже нажимаются — проверяем сами.
    if not await _windows(manager, client_actions(manager), day):
        if isinstance(event, CallbackQuery):
            await event.answer(texts.DATE_UNAVAILABLE)
        return
    manager.dialog_data[DAY] = day.isoformat()
    await manager.switch_to(Booking.time)


# --- время ---


async def time_getter(
    dialog_manager: DialogManager, client_actions: ClientActions, fmt: Formatter, **_: Any
) -> dict[str, Any]:
    name, _duration, _price = await _subject(dialog_manager, client_actions)
    day = _day(dialog_manager)
    windows = await _windows(dialog_manager, client_actions, day)
    template = texts.CHOOSE_TIME if windows else texts.NO_TIMES
    text = template.format(header=texts.header_for(name), date=texts.format_date(day))
    return {
        "text": flash.pop_flash(dialog_manager) + text,
        "windows": [(fmt.time(w).replace(":", ""), fmt.time(w)) for w in windows],
    }


async def on_time_selected(_: CallbackQuery, __: Any, manager: DialogManager, hhmm: str) -> None:
    moment = time(int(hhmm[:2]), int(hhmm[2:]))
    start = datetime.combine(_day(manager), moment, tzinfo=formatter(manager).tz)
    manager.dialog_data[START] = start.isoformat()
    await manager.switch_to(Booking.confirm)


# --- подтверждение ---


async def confirm_getter(
    dialog_manager: DialogManager, client_actions: ClientActions, fmt: Formatter, **_: Any
) -> dict[str, Any]:
    name, duration, price = await _subject(dialog_manager, client_actions)
    start = datetime.fromisoformat(dialog_manager.dialog_data[START])
    card = texts.preview_card(name, price, start, duration, fmt)
    appointment_id = _rescheduling(dialog_manager)
    if appointment_id is None:
        return {"text": texts.CONFIRM_BOOKING.format(card=card)}
    details = await client_actions.get_appointment(user_id(dialog_manager), appointment_id)
    old = fmt.when(details.appointment.starts_at)
    return {"text": texts.CONFIRM_RESCHEDULE.format(card=card, old=old)}


def _unavailable_reason(manager: DialogManager, start: datetime) -> str:
    """Окно пропало, пока клиент выбирал. Use case не говорит почему: чаще всего его заняли
    (это ловит уже проверка окна, до вставки), реже — подошло слишком близко к началу."""
    min_lead = rules(manager).min_lead
    if start - clock(manager).now() < min_lead:
        return texts.WINDOW_UNAVAILABLE.format(lead=texts.format_hours(min_lead))
    return texts.WINDOW_TAKEN


async def on_confirm(callback: CallbackQuery, _: Button, manager: DialogManager) -> None:
    actions = client_actions(manager)
    me = user_id(manager)
    start = datetime.fromisoformat(manager.dialog_data[START])
    appointment_id = _rescheduling(manager)
    try:
        if appointment_id is None:
            await actions.book(me, manager.dialog_data[SERVICE_ID], start)
        else:
            await actions.reschedule(me, appointment_id, start)
    except (WindowTakenError, WindowUnavailableError):
        flash.set_flash(manager, _unavailable_reason(manager, start))
        await manager.switch_to(Booking.time)
        return
    except TooLateToChangeError:
        lead = texts.format_hours(rules(manager).min_lead)
        await manager.done(flash.flash_result(texts.CONTACT_MASTER.format(lead=lead)))
        return
    if appointment_id is None:
        # Подтверждение с кнопками уже пришло отдельным сообщением — меню ставим под ним.
        await manager.start(
            ClientMenu.main,
            data=flash.flash_result(texts.BOOKED),
            mode=StartMode.RESET_STACK,
            show_mode=ShowMode.DELETE_AND_SEND,
        )
    else:
        await manager.done(flash.flash_result(texts.RESCHEDULED))


booking_dialog = Dialog(
    Window(
        Format("{text}"),
        Column(
            Select(
                Format("{item[1]}"),
                id="service",
                item_id_getter=lambda item: item[0],
                items="services",
                type_factory=int,
                on_click=on_service_selected,
            )
        ),
        Cancel(Const(texts.BTN_BACK)),
        state=Booking.service,
        getter=services_getter,
    ),
    Window(
        Format("{text}"),
        AvailableDatesCalendar(id="calendar", on_click=on_date_selected, when="has_dates"),
        SwitchTo(
            Const(texts.BTN_BACK),
            id="to_service",
            state=Booking.service,
            when=lambda data, *_: not data["is_reschedule"],
        ),
        Cancel(Const(texts.BTN_BACK), when="is_reschedule"),
        state=Booking.date,
        getter=date_getter,
    ),
    Window(
        Format("{text}"),
        Group(
            Select(
                Format("{item[1]}"),
                id="window",
                item_id_getter=lambda item: item[0],
                items="windows",
                on_click=on_time_selected,
            ),
            width=4,
        ),
        SwitchTo(Const(texts.BTN_BACK), id="to_date", state=Booking.date),
        state=Booking.time,
        getter=time_getter,
    ),
    Window(
        Format("{text}"),
        Button(Const(texts.BTN_CONFIRM), id="confirm", on_click=on_confirm),
        SwitchTo(Const(texts.BTN_BACK), id="to_time", state=Booking.time),
        state=Booking.confirm,
        getter=confirm_getter,
    ),
    on_start=flash.on_start,
)


def reschedule_data(appointment_id: int) -> dict[str, int]:
    return {APPOINTMENT_ID: appointment_id}
