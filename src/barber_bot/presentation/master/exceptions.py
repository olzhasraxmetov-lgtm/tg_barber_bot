"""Исключения: список будущих, удаление; добавление — период → закрыто или другие часы."""

from datetime import date
from typing import Any

from aiogram.types import CallbackQuery
from aiogram_dialog import ChatEvent, Dialog, DialogManager, Window
from aiogram_dialog.widgets.kbd import (
    Button,
    Cancel,
    Column,
    ManagedCalendar,
    Select,
    SwitchTo,
)
from aiogram_dialog.widgets.text import Const, Format

from barber_bot.application.master_actions import MasterActions
from barber_bot.application.ports import Clock
from barber_bot.domain.availability import horizon_dates
from barber_bot.domain.errors import NotFoundError
from barber_bot.domain.rules import BookingRules
from barber_bot.domain.schedule import ScheduleException
from barber_bot.presentation import flash, texts
from barber_bot.presentation.deps import clock, master_actions, rules
from barber_bot.presentation.master.common import (
    END,
    START,
    conflicts_window,
    draft_hours,
    draft_time,
    on_start_picked,
    parse_hhmm,
    remember_conflicts,
    saved_text,
    set_draft_time,
    time_options,
    time_picker,
)
from barber_bot.presentation.master.states import Exceptions
from barber_bot.presentation.widgets import CALENDAR_DATES, AvailableDatesCalendar

EXCEPTION_ID = "exception_id"
DATE_FROM = "date_from"
DATE_TO = "date_to"
# Что повторить после ответа «Отменить их и сохранить»: добавление или удаление.
PENDING = "pending"
ADD = "add"
DELETE = "delete"


def _date(manager: DialogManager, key: str) -> date:
    return date.fromisoformat(manager.dialog_data[key])


def _period(manager: DialogManager) -> str:
    return texts.format_period(_date(manager, DATE_FROM), _date(manager, DATE_TO))


def _bookable_dates(manager: DialogManager) -> list[date]:
    """Исключение имеет смысл только там, куда можно записаться, — в горизонте."""
    return horizon_dates(clock(manager).now(), rules(manager))


async def _selected(manager: DialogManager, actions: MasterActions) -> ScheduleException:
    exception_id = int(manager.dialog_data[EXCEPTION_ID])
    for exception in await actions.list_exceptions():
        if exception.id == exception_id:
            return exception
    raise NotFoundError


# --- список и удаление ---


async def list_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, **_: Any
) -> dict[str, Any]:
    exceptions = await master_actions.list_exceptions()
    if exceptions:
        rows = "\n".join(f"• {texts.exception_line(e)}" for e in exceptions)
        text = texts.EXCEPTIONS.format(rows=rows)
    else:
        text = texts.NO_EXCEPTIONS
    return {
        "text": flash.pop_flash(dialog_manager) + text,
        "exceptions": [(e.id, texts.exception_line(e)) for e in exceptions],
    }


async def on_exception_selected(
    _: CallbackQuery, __: Any, manager: DialogManager, exception_id: int
) -> None:
    manager.dialog_data[EXCEPTION_ID] = exception_id
    await manager.switch_to(Exceptions.card)


async def card_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, **_: Any
) -> dict[str, Any]:
    exception = await _selected(dialog_manager, master_actions)
    return {"text": texts.EXCEPTION_CARD.format(line=texts.exception_line(exception))}


async def _delete(manager: DialogManager, *, cancel_conflicts: bool) -> None:
    manager.dialog_data[PENDING] = DELETE
    result = await master_actions(manager).delete_exception(
        int(manager.dialog_data[EXCEPTION_ID]), cancel_conflicts=cancel_conflicts
    )
    if not result.applied:
        remember_conflicts(manager, result)
        await manager.switch_to(Exceptions.conflicts)
        return
    flash.set_flash(manager, saved_text(texts.EXCEPTION_DELETED, result))
    await manager.switch_to(Exceptions.list)


async def on_delete(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    await _delete(manager, cancel_conflicts=False)


# --- добавление: период ---


async def pick_from_getter(
    dialog_manager: DialogManager, clock: Clock, rules: BookingRules, **_: Any
) -> dict[str, Any]:
    return {"text": texts.EXC_PICK_FROM, CALENDAR_DATES: horizon_dates(clock.now(), rules)}


async def on_from_selected(
    event: ChatEvent, _: ManagedCalendar, manager: DialogManager, day: date, /
) -> None:
    if day not in _bookable_dates(manager):
        if isinstance(event, CallbackQuery):
            await event.answer(texts.DATE_UNAVAILABLE)
        return
    manager.dialog_data[DATE_FROM] = day.isoformat()
    await manager.switch_to(Exceptions.pick_to)


async def pick_to_getter(
    dialog_manager: DialogManager, clock: Clock, rules: BookingRules, **_: Any
) -> dict[str, Any]:
    date_from = _date(dialog_manager, DATE_FROM)
    label = texts.format_date(date_from)
    return {
        "text": texts.EXC_PICK_TO.format(date_from=label),
        CALENDAR_DATES: [d for d in horizon_dates(clock.now(), rules) if d >= date_from],
        "date_from": label,
    }


async def _set_period(manager: DialogManager, date_to: date) -> None:
    manager.dialog_data[DATE_TO] = date_to.isoformat()
    set_draft_time(manager, START, None)
    set_draft_time(manager, END, None)
    await manager.switch_to(Exceptions.kind)


async def on_to_selected(
    event: ChatEvent, _: ManagedCalendar, manager: DialogManager, day: date, /
) -> None:
    if day < _date(manager, DATE_FROM) or day not in _bookable_dates(manager):
        if isinstance(event, CallbackQuery):
            await event.answer(texts.DATE_UNAVAILABLE)
        return
    await _set_period(manager, day)


async def on_one_day(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    await _set_period(manager, _date(manager, DATE_FROM))


# --- добавление: что в эти дни ---


async def kind_getter(dialog_manager: DialogManager, **_: Any) -> dict[str, Any]:
    return {"text": texts.EXC_KIND.format(period=_period(dialog_manager))}


async def _add(manager: DialogManager, *, cancel_conflicts: bool) -> None:
    manager.dialog_data[PENDING] = ADD
    exception = ScheduleException(
        _date(manager, DATE_FROM), _date(manager, DATE_TO), draft_hours(manager)
    )
    result = await master_actions(manager).add_exception(
        exception, cancel_conflicts=cancel_conflicts
    )
    if not result.applied:
        remember_conflicts(manager, result)
        await manager.switch_to(Exceptions.conflicts)
        return
    flash.set_flash(manager, saved_text(texts.EXCEPTION_ADDED, result))
    await manager.switch_to(Exceptions.list)


async def on_closed(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    # Могли начать выбирать часы и вернуться: закрытый день — без часов.
    set_draft_time(manager, START, None)
    set_draft_time(manager, END, None)
    await _add(manager, cancel_conflicts=False)


async def pick_start_getter(
    dialog_manager: DialogManager, rules: BookingRules, **_: Any
) -> dict[str, Any]:
    return {
        "text": texts.EXC_PICK_START.format(period=_period(dialog_manager)),
        "times": time_options(rules)[:-1],
    }


async def on_start_selected(_: CallbackQuery, __: Any, manager: DialogManager, hhmm: str) -> None:
    # Конец ещё не выбран — on_start_picked всегда ведёт к нему.
    await on_start_picked(manager, hhmm, end_state=Exceptions.pick_end)


async def pick_end_getter(
    dialog_manager: DialogManager, rules: BookingRules, **_: Any
) -> dict[str, Any]:
    return {
        "text": texts.EXC_PICK_END.format(period=_period(dialog_manager)),
        "times": time_options(rules, after=draft_time(dialog_manager, START)),
    }


async def on_end_selected(_: CallbackQuery, __: Any, manager: DialogManager, hhmm: str) -> None:
    set_draft_time(manager, END, parse_hhmm(hhmm))
    await _add(manager, cancel_conflicts=False)


# --- конфликты ---


async def on_apply_conflicts(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    if manager.dialog_data.get(PENDING) == DELETE:
        await _delete(manager, cancel_conflicts=True)
    else:
        await _add(manager, cancel_conflicts=True)


async def on_reject_conflicts(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    flash.set_flash(manager, texts.NOT_SAVED)
    await manager.switch_to(Exceptions.list)


exceptions_dialog = Dialog(
    Window(
        Format("{text}"),
        Column(
            Select(
                Format("{item[1]}"),
                id="exception",
                item_id_getter=lambda item: item[0],
                items="exceptions",
                type_factory=int,
                on_click=on_exception_selected,
            )
        ),
        SwitchTo(Const(texts.BTN_ADD_EXCEPTION), id="add", state=Exceptions.pick_from),
        Cancel(Const(texts.BTN_MENU)),
        state=Exceptions.list,
        getter=list_getter,
    ),
    Window(
        Format("{text}"),
        Button(Const(texts.BTN_DELETE), id="delete", on_click=on_delete),
        SwitchTo(Const(texts.BTN_BACK), id="to_list", state=Exceptions.list),
        state=Exceptions.card,
        getter=card_getter,
    ),
    Window(
        Format("{text}"),
        AvailableDatesCalendar(id="from", on_click=on_from_selected),
        SwitchTo(Const(texts.BTN_BACK), id="to_list", state=Exceptions.list),
        state=Exceptions.pick_from,
        getter=pick_from_getter,
    ),
    Window(
        Format("{text}"),
        Button(Format(texts.BTN_ONE_DAY), id="one_day", on_click=on_one_day),
        AvailableDatesCalendar(id="to", on_click=on_to_selected),
        SwitchTo(Const(texts.BTN_BACK), id="to_from", state=Exceptions.pick_from),
        state=Exceptions.pick_to,
        getter=pick_to_getter,
    ),
    Window(
        Format("{text}"),
        Button(Const(texts.BTN_CLOSED), id="closed", on_click=on_closed),
        SwitchTo(Const(texts.BTN_CHANGED_HOURS), id="hours", state=Exceptions.pick_start),
        SwitchTo(Const(texts.BTN_BACK), id="to_to", state=Exceptions.pick_to),
        state=Exceptions.kind,
        getter=kind_getter,
    ),
    Window(
        Format("{text}"),
        time_picker(on_start_selected),
        SwitchTo(Const(texts.BTN_BACK), id="to_kind", state=Exceptions.kind),
        state=Exceptions.pick_start,
        getter=pick_start_getter,
    ),
    Window(
        Format("{text}"),
        time_picker(on_end_selected),
        SwitchTo(Const(texts.BTN_BACK), id="to_start", state=Exceptions.pick_start),
        state=Exceptions.pick_end,
        getter=pick_end_getter,
    ),
    conflicts_window(Exceptions.conflicts, on_apply_conflicts, on_reject_conflicts),
    on_start=flash.on_start,
)
