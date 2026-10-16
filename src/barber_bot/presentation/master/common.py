"""Общее для графика и исключений: выбор часов кнопками и экран конфликтов с записями."""

from datetime import datetime, time, timedelta
from typing import Any

from aiogram.fsm.state import State
from aiogram_dialog import DialogManager, Window
from aiogram_dialog.widgets.kbd import Button, Group, Select
from aiogram_dialog.widgets.kbd.button import OnClick
from aiogram_dialog.widgets.kbd.select import OnItemClick
from aiogram_dialog.widgets.text import Const, Format

from barber_bot.application.master_actions import ScheduleChangeResult
from barber_bot.domain.rules import BookingRules
from barber_bot.domain.schedule import WorkingHours
from barber_bot.presentation import texts
from barber_bot.presentation.deps import formatter

# Черновик часов в dialog_data: «HH:MM».
START = "start"
END = "end"
CONFLICTS = "conflicts"

# Кнопки времени: рабочий день барбера укладывается в этот диапазон.
FIRST_TIME = time(6, 0)
LAST_TIME = time(23, 30)


def time_options(rules: BookingRules, *, after: time | None = None) -> list[tuple[str, str]]:
    """Времена с шагом сетки: (id «HHMM», подпись «HH:MM»); `after` — только позже него."""
    options = []
    moment = datetime.combine(datetime.min, FIRST_TIME)
    last = datetime.combine(datetime.min, LAST_TIME)
    while moment <= last:
        t = moment.time()
        if after is None or t > after:
            options.append((f"{t:%H%M}", f"{t:%H:%M}"))
        moment += timedelta(minutes=rules.grid_step_minutes)
    return options


def parse_hhmm(value: str) -> time:
    """«1030» или «10:30» → time(10, 30)."""
    digits = value.replace(":", "")
    return time(int(digits[:2]), int(digits[2:]))


def draft_time(manager: DialogManager, key: str) -> time | None:
    value = manager.dialog_data.get(key)
    return parse_hhmm(value) if value else None


def set_draft_time(manager: DialogManager, key: str, value: time | None) -> None:
    manager.dialog_data[key] = f"{value:%H:%M}" if value else None


def draft_hours(manager: DialogManager) -> WorkingHours | None:
    start, end = draft_time(manager, START), draft_time(manager, END)
    return WorkingHours(start, end) if start and end else None


def time_picker(on_click: OnItemClick[Any, str]) -> Group:
    return Group(
        Select(
            Format("{item[1]}"),
            id="time",
            item_id_getter=lambda item: item[0],
            items="times",
            on_click=on_click,
        ),
        width=5,
    )


async def on_start_picked(manager: DialogManager, hhmm: str, *, end_state: State) -> bool:
    """Записать начало. True — конец ещё нужно выбрать (его нет или он не позже начала)."""
    start = parse_hhmm(hhmm)
    set_draft_time(manager, START, start)
    end = draft_time(manager, END)
    if end is None or end <= start:
        set_draft_time(manager, END, None)
        await manager.switch_to(end_state)
        return True
    return False


# --- конфликты с записями ---


def remember_conflicts(manager: DialogManager, result: ScheduleChangeResult) -> None:
    manager.dialog_data[CONFLICTS] = texts.conflicts(result.conflicts, formatter(manager))


def saved_text(text: str, result: ScheduleChangeResult) -> str:
    """«График сохранён. Отменено записей: 2.»"""
    if result.conflicts:
        return text + texts.CONFLICTS_CANCELLED.format(count=len(result.conflicts))
    return text


async def conflicts_getter(dialog_manager: DialogManager, **_: Any) -> dict[str, Any]:
    return {"text": dialog_manager.dialog_data.get(CONFLICTS, "")}


def conflicts_window(state: State, on_apply: OnClick, on_reject: OnClick) -> Window:
    """«Отменить их и сохранить» повторяет изменение с cancel_conflicts=True."""
    return Window(
        Format("{text}"),
        Button(Const(texts.BTN_CANCEL_CONFLICTS), id="apply", on_click=on_apply),
        Button(Const(texts.BTN_DONT_SAVE), id="reject", on_click=on_reject),
        state=state,
        getter=conflicts_getter,
    )
