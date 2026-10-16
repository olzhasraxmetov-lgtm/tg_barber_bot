"""Ручная запись: имя → телефон → услуга → дата → свободное окно → подтверждение.

Окна те же, что видит клиент, но без минимального запаса до начала.
"""

from datetime import date, datetime
from html import escape
from typing import Any

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import ChatEvent, Dialog, DialogManager, Window
from aiogram_dialog.widgets.input import ManagedTextInput, TextInput
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

from barber_bot.application.master_actions import MasterActions
from barber_bot.domain.entities import Service, clean_name
from barber_bot.domain.errors import NotFoundError, WindowTakenError, WindowUnavailableError
from barber_bot.domain.rules import BookingRules
from barber_bot.presentation import flash, texts
from barber_bot.presentation.deps import formatter, master_actions
from barber_bot.presentation.master.common import parse_hhmm
from barber_bot.presentation.master.states import ManualBooking
from barber_bot.presentation.texts import Formatter
from barber_bot.presentation.widgets import CALENDAR_DATES, AvailableDatesCalendar

NAME = "name"
PHONE = "phone"
SERVICE_ID = "service_id"
DAY = "day"
START = "start"


def _name(manager: DialogManager) -> str:
    return str(manager.dialog_data[NAME])


def _service_id(manager: DialogManager) -> int:
    return int(manager.dialog_data[SERVICE_ID])


def _day(manager: DialogManager) -> date:
    return date.fromisoformat(manager.dialog_data[DAY])


async def _bookable_services(actions: MasterActions) -> list[Service]:
    return [s for s in await actions.list_services() if not s.is_hidden]


async def _service(manager: DialogManager, actions: MasterActions) -> Service:
    service_id = _service_id(manager)
    for service in await actions.list_services():
        if service.id == service_id:
            return service
    raise NotFoundError


# --- имя и телефон ---


async def on_name_entered(
    _: Message, __: ManagedTextInput[str], manager: DialogManager, name: str
) -> None:
    manager.dialog_data[NAME] = name
    await manager.switch_to(ManualBooking.phone)


async def phone_getter(dialog_manager: DialogManager, **_: Any) -> dict[str, Any]:
    return {"text": texts.MANUAL_ASK_PHONE.format(name=escape(_name(dialog_manager)))}


async def on_phone_entered(
    _: Message, __: ManagedTextInput[str], manager: DialogManager, raw: str
) -> None:
    # Неверный номер — InvalidPhoneError, его текст покажет общий обработчик ошибок.
    manager.dialog_data[PHONE] = master_actions(manager).normalize_phone(raw)
    await manager.switch_to(ManualBooking.service)


# --- услуга ---


async def services_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, fmt: Formatter, **_: Any
) -> dict[str, Any]:
    services = await _bookable_services(master_actions)
    template = texts.MANUAL_CHOOSE_SERVICE if services else texts.NO_MASTER_SERVICES
    return {
        "text": template.format(name=escape(_name(dialog_manager))),
        "services": [(s.id, texts.service_line(s, fmt)) for s in services],
    }


async def on_service_selected(
    _: CallbackQuery, __: Any, manager: DialogManager, service_id: int
) -> None:
    manager.dialog_data[SERVICE_ID] = service_id
    await manager.switch_to(ManualBooking.date)


# --- дата и время ---


async def date_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, rules: BookingRules, **_: Any
) -> dict[str, Any]:
    service = await _service(dialog_manager, master_actions)
    dates = await master_actions.available_dates(_service_id(dialog_manager))
    header = texts.manual_header(_name(dialog_manager), service.name)
    template = texts.CHOOSE_DATE if dates else texts.NO_DATES
    return {
        "text": template.format(header=header, days=rules.horizon_days),
        CALENDAR_DATES: dates,
        "has_dates": bool(dates),
    }


async def on_date_selected(
    event: ChatEvent, _: ManagedCalendar, manager: DialogManager, day: date, /
) -> None:
    if not await master_actions(manager).free_windows(_service_id(manager), day):
        if isinstance(event, CallbackQuery):
            await event.answer(texts.DATE_UNAVAILABLE)
        return
    manager.dialog_data[DAY] = day.isoformat()
    await manager.switch_to(ManualBooking.time)


async def time_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, fmt: Formatter, **_: Any
) -> dict[str, Any]:
    service = await _service(dialog_manager, master_actions)
    day = _day(dialog_manager)
    windows = await master_actions.free_windows(_service_id(dialog_manager), day)
    template = texts.CHOOSE_TIME if windows else texts.NO_TIMES
    header = texts.manual_header(_name(dialog_manager), service.name)
    text = template.format(header=header, date=texts.format_date(day))
    return {
        "text": flash.pop_flash(dialog_manager) + text,
        "windows": [(fmt.time(w).replace(":", ""), fmt.time(w)) for w in windows],
    }


async def on_time_selected(_: CallbackQuery, __: Any, manager: DialogManager, hhmm: str) -> None:
    start = datetime.combine(_day(manager), parse_hhmm(hhmm), tzinfo=formatter(manager).tz)
    manager.dialog_data[START] = start.isoformat()
    await manager.switch_to(ManualBooking.confirm)


# --- подтверждение ---


async def confirm_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, fmt: Formatter, **_: Any
) -> dict[str, Any]:
    service = await _service(dialog_manager, master_actions)
    data = dialog_manager.dialog_data
    start = datetime.fromisoformat(data[START])
    client = f"👤 {escape(data[NAME])} · {texts.format_phone(data[PHONE])}"
    card = (
        client
        + "\n"
        + texts.preview_card(service.name, service.price, start, service.duration_minutes, fmt)
    )
    return {"text": texts.CONFIRM_MANUAL.format(card=card)}


async def on_confirm(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    data = manager.dialog_data
    try:
        details = await master_actions(manager).manual_booking(
            data[NAME], data[PHONE], _service_id(manager), datetime.fromisoformat(data[START])
        )
    except (WindowTakenError, WindowUnavailableError):
        flash.set_flash(manager, texts.WINDOW_TAKEN)
        await manager.switch_to(ManualBooking.time)
        return
    notified = details.client.telegram_id is not None
    await manager.done(
        flash.flash_result(texts.MANUAL_BOOKED_NOTIFIED if notified else texts.MANUAL_BOOKED)
    )


manual_booking_dialog = Dialog(
    Window(
        Const(texts.MANUAL_ASK_NAME),
        TextInput(id="name", type_factory=clean_name, on_success=on_name_entered),
        Cancel(Const(texts.BTN_BACK)),
        state=ManualBooking.name,
    ),
    Window(
        Format("{text}"),
        TextInput(id="phone", on_success=on_phone_entered),
        SwitchTo(Const(texts.BTN_BACK), id="to_name", state=ManualBooking.name),
        state=ManualBooking.phone,
        getter=phone_getter,
    ),
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
        SwitchTo(Const(texts.BTN_BACK), id="to_phone", state=ManualBooking.phone),
        state=ManualBooking.service,
        getter=services_getter,
    ),
    Window(
        Format("{text}"),
        AvailableDatesCalendar(id="calendar", on_click=on_date_selected, when="has_dates"),
        SwitchTo(Const(texts.BTN_BACK), id="to_service", state=ManualBooking.service),
        state=ManualBooking.date,
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
        SwitchTo(Const(texts.BTN_BACK), id="to_date", state=ManualBooking.date),
        state=ManualBooking.time,
        getter=time_getter,
    ),
    Window(
        Format("{text}"),
        Button(Const(texts.BTN_CONFIRM), id="confirm", on_click=on_confirm),
        SwitchTo(Const(texts.BTN_BACK), id="to_time", state=ManualBooking.time),
        state=ManualBooking.confirm,
        getter=confirm_getter,
    ),
)
