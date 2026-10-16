"""Расписание дня → карточка записи: отмена с необязательной причиной, неявка."""

from datetime import date, timedelta
from typing import Any

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import ChatEvent, Dialog, DialogManager, Window
from aiogram_dialog.widgets.input import ManagedTextInput, TextInput
from aiogram_dialog.widgets.kbd import (
    Button,
    Cancel,
    Column,
    ManagedCalendar,
    Row,
    Select,
    SwitchTo,
)
from aiogram_dialog.widgets.text import Const, Format

from barber_bot.application.master_actions import MasterActions
from barber_bot.application.ports import Clock
from barber_bot.domain.rules import BookingRules
from barber_bot.presentation import flash, texts
from barber_bot.presentation.deps import clock, master_actions, rules
from barber_bot.presentation.master.states import DaySchedule
from barber_bot.presentation.texts import Formatter
from barber_bot.presentation.widgets import CALENDAR_DATES, AvailableDatesCalendar

DAY = "day"
APPOINTMENT_ID = "appointment_id"
# Столько символов причины отмены помещается в базу.
REASON_LIMIT = 200


def day_data(day: date) -> dict[str, str]:
    return {DAY: day.isoformat()}


def card_data(appointment_id: int) -> dict[str, int]:
    """start_data, чтобы открыть сразу карточку — например, из уведомления."""
    return {APPOINTMENT_ID: appointment_id}


def _day(manager: DialogManager) -> date:
    return date.fromisoformat(manager.dialog_data[DAY])


def _selected(manager: DialogManager) -> int:
    return int(manager.dialog_data[APPOINTMENT_ID])


def _schedule_dates(today: date, rules: BookingRules) -> list[date]:
    """Даты, которые можно открыть: горизонт записи вперёд и столько же назад — чтобы
    отметить неявку на прошедшей записи."""
    days = rules.horizon_days
    return [today + timedelta(days=shift) for shift in range(-days, days)]


# --- выбор даты ---


async def pick_date_getter(
    dialog_manager: DialogManager, clock: Clock, rules: BookingRules, **_: Any
) -> dict[str, Any]:
    return {
        "text": texts.PICK_SCHEDULE_DATE,
        CALENDAR_DATES: _schedule_dates(clock.now().date(), rules),
        "has_day": DAY in dialog_manager.dialog_data,
    }


async def on_date_selected(
    event: ChatEvent, _: ManagedCalendar, manager: DialogManager, day: date, /
) -> None:
    if day not in _schedule_dates(clock(manager).now().date(), rules(manager)):
        if isinstance(event, CallbackQuery):
            await event.answer(texts.DATE_UNAVAILABLE)
        return
    manager.dialog_data[DAY] = day.isoformat()
    await manager.switch_to(DaySchedule.day)


# --- день ---


async def day_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, fmt: Formatter, **_: Any
) -> dict[str, Any]:
    day = _day(dialog_manager)
    appointments = await master_actions.schedule_for(day)
    return {
        "text": flash.pop_flash(dialog_manager) + texts.day_schedule(day, appointments, fmt),
        "appointments": [
            (d.appointment.id, texts.schedule_button(d, fmt))
            for d in sorted(appointments, key=lambda d: d.appointment.starts_at)
        ],
        "prev_day": texts.format_date(day - timedelta(days=1)),
        "next_day": texts.format_date(day + timedelta(days=1)),
    }


def _shift_day(days: int) -> Any:
    async def on_click(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
        manager.dialog_data[DAY] = (_day(manager) + timedelta(days=days)).isoformat()

    return on_click


async def on_appointment_selected(
    _: CallbackQuery, __: Any, manager: DialogManager, appointment_id: int
) -> None:
    manager.dialog_data[APPOINTMENT_ID] = appointment_id
    await manager.switch_to(DaySchedule.card)


# --- карточка ---


async def card_getter(
    dialog_manager: DialogManager,
    master_actions: MasterActions,
    fmt: Formatter,
    clock: Clock,
    **_: Any,
) -> dict[str, Any]:
    details = await master_actions.get_appointment(_selected(dialog_manager))
    a = details.appointment
    # Открыли из уведомления — «← К расписанию» ведёт в день этой записи.
    dialog_manager.dialog_data.setdefault(DAY, a.starts_at.astimezone(fmt.tz).date().isoformat())
    started = a.starts_at <= clock.now()
    return {
        "text": flash.pop_flash(dialog_manager) + texts.master_card(details, fmt),
        "can_cancel": a.is_active and not started,
        "can_mark_no_show": a.is_active and started and not a.no_show,
        "can_undo_no_show": a.is_active and a.no_show,
    }


def _set_no_show(value: bool) -> Any:
    async def on_click(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
        await master_actions(manager).set_no_show(_selected(manager), value)
        flash.set_flash(manager, texts.NO_SHOW_SET if value else texts.NO_SHOW_CLEARED)

    return on_click


# --- отмена ---


async def cancel_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, fmt: Formatter, **_: Any
) -> dict[str, Any]:
    details = await master_actions.get_appointment(_selected(dialog_manager))
    text = texts.ASK_MASTER_CANCEL.format(
        card=texts.appointment_card(details, fmt, with_client=True)
    )
    if details.client.telegram_id is None:
        text += "\n\n" + texts.NO_TELEGRAM_WARNING
    return {"text": text}


async def _cancel(manager: DialogManager, reason: str | None) -> None:
    details = await master_actions(manager).cancel(_selected(manager), reason)
    text = texts.MASTER_CANCELLED
    if details.client.telegram_id is not None:
        text += texts.CLIENT_NOTIFIED
    flash.set_flash(manager, text)
    await manager.switch_to(DaySchedule.day)


def _reason(raw: str) -> str:
    reason = " ".join(raw.split())
    if len(reason) > REASON_LIMIT:
        raise ValueError(reason)
    return reason


async def on_reason_entered(
    _: Message, __: ManagedTextInput[str], manager: DialogManager, reason: str
) -> None:
    await _cancel(manager, reason or None)


async def on_reason_error(
    message: Message, _: ManagedTextInput[str], __: DialogManager, ___: ValueError
) -> None:
    await message.answer(texts.CANCEL_REASON_TOO_LONG.format(limit=REASON_LIMIT))


async def on_cancel_without_reason(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    await _cancel(manager, None)


day_schedule_dialog = Dialog(
    Window(
        Format("{text}"),
        AvailableDatesCalendar(id="calendar", on_click=on_date_selected),
        SwitchTo(Const(texts.BTN_BACK), id="to_day", state=DaySchedule.day, when="has_day"),
        Cancel(Const(texts.BTN_MENU)),
        state=DaySchedule.pick_date,
        getter=pick_date_getter,
    ),
    Window(
        Format("{text}"),
        Column(
            Select(
                Format("{item[1]}"),
                id="appointment",
                item_id_getter=lambda item: item[0],
                items="appointments",
                type_factory=int,
                on_click=on_appointment_selected,
            )
        ),
        Row(
            Button(Format(texts.BTN_PREV_DAY), id="prev", on_click=_shift_day(-1)),
            Button(Format(texts.BTN_NEXT_DAY), id="next", on_click=_shift_day(1)),
        ),
        SwitchTo(Const(texts.BTN_PICK_DATE), id="pick_date", state=DaySchedule.pick_date),
        Cancel(Const(texts.BTN_MENU)),
        state=DaySchedule.day,
        getter=day_getter,
    ),
    Window(
        Format("{text}"),
        SwitchTo(Const(texts.BTN_CANCEL), id="cancel", state=DaySchedule.cancel, when="can_cancel"),
        Button(
            Const(texts.BTN_NO_SHOW),
            id="no_show",
            on_click=_set_no_show(True),
            when="can_mark_no_show",
        ),
        Button(
            Const(texts.BTN_UNDO_NO_SHOW),
            id="undo_no_show",
            on_click=_set_no_show(False),
            when="can_undo_no_show",
        ),
        SwitchTo(Const(texts.BTN_TO_SCHEDULE), id="to_day", state=DaySchedule.day),
        Cancel(Const(texts.BTN_MENU)),
        state=DaySchedule.card,
        getter=card_getter,
    ),
    Window(
        Format("{text}"),
        TextInput(
            id="reason",
            type_factory=_reason,
            on_success=on_reason_entered,
            on_error=on_reason_error,
        ),
        Button(
            Const(texts.BTN_CANCEL_NO_REASON), id="no_reason", on_click=on_cancel_without_reason
        ),
        SwitchTo(Const(texts.BTN_BACK), id="back", state=DaySchedule.card),
        state=DaySchedule.cancel,
        getter=cancel_getter,
    ),
    on_start=flash.on_start,
)
