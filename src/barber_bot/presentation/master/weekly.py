"""График: часы или выходной по дням недели. День правится черновиком и сохраняется целиком."""

from typing import Any

from aiogram.types import CallbackQuery
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.kbd import Button, Cancel, Column, Row, Select, SwitchTo
from aiogram_dialog.widgets.text import Const, Format

from barber_bot.application.master_actions import MasterActions
from barber_bot.domain.rules import BookingRules
from barber_bot.domain.schedule import WeeklySchedule, WorkingHours
from barber_bot.presentation import flash, texts
from barber_bot.presentation.deps import master_actions
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
from barber_bot.presentation.master.states import WeeklyHours

WEEKDAY = "weekday"


def _weekday(manager: DialogManager) -> int:
    return int(manager.dialog_data[WEEKDAY])


async def week_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, rules: BookingRules, **_: Any
) -> dict[str, Any]:
    schedule = await master_actions.get_weekly_schedule()
    lunch = WorkingHours(rules.lunch_start, rules.lunch_end)
    return {
        "text": flash.pop_flash(dialog_manager) + texts.weekly(schedule.days, lunch),
        "weekdays": [(day, texts.weekday_button(day, schedule.hours_on(day))) for day in range(7)],
    }


async def on_weekday_selected(
    _: CallbackQuery, __: Any, manager: DialogManager, weekday: int
) -> None:
    hours = (await master_actions(manager).get_weekly_schedule()).hours_on(weekday)
    manager.dialog_data[WEEKDAY] = weekday
    set_draft_time(manager, START, hours.start if hours else None)
    set_draft_time(manager, END, hours.end if hours else None)
    await manager.switch_to(WeeklyHours.day)


# --- день ---


async def day_getter(dialog_manager: DialogManager, **_: Any) -> dict[str, Any]:
    hours = draft_hours(dialog_manager)
    weekday = texts.WEEKDAYS_FULL[_weekday(dialog_manager)]
    span = texts.format_hours_span(hours) if hours else texts.DAY_OFF.capitalize()
    return {
        "text": texts.WEEKLY_DAY.format(weekday=weekday, hours=span),
        "is_working": hours is not None,
        "start": f"{hours.start:%H:%M}" if hours else "",
        "end": f"{hours.end:%H:%M}" if hours else "",
    }


async def on_day_off(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    set_draft_time(manager, START, None)
    set_draft_time(manager, END, None)


async def on_workday(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    await manager.switch_to(WeeklyHours.pick_start)


async def pick_start_getter(rules: BookingRules, **_: Any) -> dict[str, Any]:
    # Последнее время не может быть началом: после него не остаётся конца.
    return {"text": texts.PICK_START, "times": time_options(rules)[:-1]}


async def on_start_selected(_: CallbackQuery, __: Any, manager: DialogManager, hhmm: str) -> None:
    if not await on_start_picked(manager, hhmm, end_state=WeeklyHours.pick_end):
        await manager.switch_to(WeeklyHours.day)


async def pick_end_getter(
    dialog_manager: DialogManager, rules: BookingRules, **_: Any
) -> dict[str, Any]:
    return {
        "text": texts.PICK_END,
        "times": time_options(rules, after=draft_time(dialog_manager, START)),
    }


async def on_end_selected(_: CallbackQuery, __: Any, manager: DialogManager, hhmm: str) -> None:
    set_draft_time(manager, END, parse_hhmm(hhmm))
    await manager.switch_to(WeeklyHours.day)


# --- сохранение ---


async def _save(manager: DialogManager, *, cancel_conflicts: bool) -> None:
    actions = master_actions(manager)
    days = dict((await actions.get_weekly_schedule()).days)
    hours = draft_hours(manager)
    if hours is None:
        days.pop(_weekday(manager), None)
    else:
        days[_weekday(manager)] = hours
    result = await actions.set_weekly_schedule(
        WeeklySchedule(days), cancel_conflicts=cancel_conflicts
    )
    if not result.applied:
        remember_conflicts(manager, result)
        await manager.switch_to(WeeklyHours.conflicts)
        return
    flash.set_flash(manager, saved_text(texts.WEEKLY_SAVED, result))
    await manager.switch_to(WeeklyHours.week)


async def on_save(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    await _save(manager, cancel_conflicts=False)


async def on_apply_conflicts(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    await _save(manager, cancel_conflicts=True)


async def on_reject_conflicts(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    flash.set_flash(manager, texts.NOT_SAVED)
    await manager.switch_to(WeeklyHours.week)


weekly_dialog = Dialog(
    Window(
        Format("{text}"),
        Column(
            Select(
                Format("{item[1]}"),
                id="weekday",
                item_id_getter=lambda item: item[0],
                items="weekdays",
                type_factory=int,
                on_click=on_weekday_selected,
            )
        ),
        Cancel(Const(texts.BTN_MENU)),
        state=WeeklyHours.week,
        getter=week_getter,
    ),
    Window(
        Format("{text}"),
        Row(
            SwitchTo(Format(texts.BTN_START_TIME), id="start", state=WeeklyHours.pick_start),
            SwitchTo(Format(texts.BTN_END_TIME), id="end", state=WeeklyHours.pick_end),
            when="is_working",
        ),
        Button(Const(texts.BTN_DAY_OFF), id="day_off", on_click=on_day_off, when="is_working"),
        Button(
            Const(texts.BTN_WORKDAY),
            id="workday",
            on_click=on_workday,
            when=lambda data, *_: not data["is_working"],
        ),
        Button(Const(texts.BTN_SAVE), id="save", on_click=on_save),
        SwitchTo(Const(texts.BTN_BACK), id="to_week", state=WeeklyHours.week),
        state=WeeklyHours.day,
        getter=day_getter,
    ),
    Window(
        Format("{text}"),
        time_picker(on_start_selected),
        SwitchTo(Const(texts.BTN_BACK), id="to_day", state=WeeklyHours.day),
        state=WeeklyHours.pick_start,
        getter=pick_start_getter,
    ),
    Window(
        Format("{text}"),
        time_picker(on_end_selected),
        SwitchTo(Const(texts.BTN_BACK), id="to_day", state=WeeklyHours.day),
        state=WeeklyHours.pick_end,
        getter=pick_end_getter,
    ),
    conflicts_window(WeeklyHours.conflicts, on_apply_conflicts, on_reject_conflicts),
    on_start=flash.on_start,
)
