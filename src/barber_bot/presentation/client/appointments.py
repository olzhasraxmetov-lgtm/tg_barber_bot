"""Мои записи: предстоящие → карточка → отмена с подтверждением или перенос."""

from datetime import datetime
from typing import Any

from aiogram.types import CallbackQuery
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.kbd import Button, Cancel, Column, Select, Start, SwitchTo
from aiogram_dialog.widgets.text import Const, Format

from barber_bot.application.client_actions import ClientActions
from barber_bot.application.notifications import AppointmentDetails
from barber_bot.application.ports import Clock
from barber_bot.domain.errors import TooLateToChangeError
from barber_bot.domain.rules import BookingRules
from barber_bot.presentation import flash, texts
from barber_bot.presentation.client.booking import reschedule_data
from barber_bot.presentation.client.states import Booking, MyAppointments
from barber_bot.presentation.deps import client_actions, user_id
from barber_bot.presentation.texts import Formatter

APPOINTMENT_ID = "appointment_id"


def _selected(manager: DialogManager) -> int:
    return int(manager.dialog_data[APPOINTMENT_ID])


def card_data(appointment_id: int) -> dict[str, int]:
    """start_data, чтобы открыть диалог сразу на карточке (или на вопросе об отмене)."""
    return {APPOINTMENT_ID: appointment_id}


# --- список ---


async def list_getter(
    dialog_manager: DialogManager, client_actions: ClientActions, fmt: Formatter, **_: Any
) -> dict[str, Any]:
    appointments = await client_actions.my_appointments(user_id(dialog_manager))
    text = texts.MY_APPOINTMENTS if appointments else texts.NO_APPOINTMENTS
    return {
        "text": flash.pop_flash(dialog_manager) + text,
        "appointments": [
            (d.appointment.id, texts.appointment_button(d, fmt)) for d in appointments
        ],
        "is_empty": not appointments,
    }


async def on_appointment_selected(
    _: CallbackQuery, __: Any, manager: DialogManager, appointment_id: int
) -> None:
    manager.dialog_data[APPOINTMENT_ID] = appointment_id
    await manager.switch_to(MyAppointments.card)


# --- карточка ---


def _status_note(
    details: AppointmentDetails, can_change: bool, now: datetime, rules: BookingRules
) -> str:
    a = details.appointment
    if not a.is_active:
        return texts.APPOINTMENT_CANCELLED
    if can_change:
        return ""
    # Активная, но менять нельзя: либо уже началась (открыли из старого уведомления),
    # либо до начала меньше запаса.
    if a.starts_at <= now:
        return texts.APPOINTMENT_PAST
    return texts.CONTACT_MASTER.format(lead=texts.format_hours(rules.min_lead))


async def card_getter(
    dialog_manager: DialogManager,
    client_actions: ClientActions,
    fmt: Formatter,
    rules: BookingRules,
    clock: Clock,
    **_: Any,
) -> dict[str, Any]:
    me, appointment_id = user_id(dialog_manager), _selected(dialog_manager)
    details = await client_actions.get_appointment(me, appointment_id)
    can_change = await client_actions.can_change(me, appointment_id)
    parts = [
        flash.pop_flash(dialog_manager) + texts.appointment_card(details, fmt, with_client=False),
        _status_note(details, can_change, clock.now(), rules),
    ]
    return {"text": "\n\n".join(p for p in parts if p), "can_change": can_change}


async def on_reschedule(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    await manager.start(Booking.date, data=reschedule_data(_selected(manager)))


# --- отмена ---


async def cancel_getter(
    dialog_manager: DialogManager, client_actions: ClientActions, fmt: Formatter, **_: Any
) -> dict[str, Any]:
    details = await client_actions.get_appointment(
        user_id(dialog_manager), _selected(dialog_manager)
    )
    card = texts.appointment_card(details, fmt, with_client=False)
    return {"text": texts.ASK_CANCEL.format(card=card)}


async def on_cancel_confirmed(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    try:
        await client_actions(manager).cancel(user_id(manager), _selected(manager))
    except TooLateToChangeError:
        # Карточка сама покажет «свяжитесь с мастером».
        await manager.switch_to(MyAppointments.card)
        return
    flash.set_flash(manager, texts.CANCELLED)
    await manager.switch_to(MyAppointments.list)


my_appointments_dialog = Dialog(
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
        Start(Const(texts.BTN_BOOK), id="book", state=Booking.service, when="is_empty"),
        Cancel(Const(texts.BTN_MENU)),
        state=MyAppointments.list,
        getter=list_getter,
    ),
    Window(
        Format("{text}"),
        Button(
            Const(texts.BTN_RESCHEDULE), id="reschedule", on_click=on_reschedule, when="can_change"
        ),
        SwitchTo(
            Const(texts.BTN_CANCEL), id="cancel", state=MyAppointments.cancel, when="can_change"
        ),
        SwitchTo(Const(texts.BTN_TO_LIST), id="to_list", state=MyAppointments.list),
        Cancel(Const(texts.BTN_MENU)),
        state=MyAppointments.card,
        getter=card_getter,
    ),
    Window(
        Format("{text}"),
        Button(Const(texts.BTN_YES_CANCEL), id="yes", on_click=on_cancel_confirmed),
        SwitchTo(Const(texts.BTN_NO_KEEP), id="no", state=MyAppointments.card),
        state=MyAppointments.cancel,
        getter=cancel_getter,
    ),
    on_start=flash.on_start,
    on_process_result=flash.on_result,
)
