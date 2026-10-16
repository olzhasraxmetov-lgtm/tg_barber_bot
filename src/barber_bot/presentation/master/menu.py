"""Меню мастера и переключатель режимов."""

from datetime import timedelta
from typing import Any

from aiogram.types import CallbackQuery
from aiogram_dialog import Dialog, DialogManager, ShowMode, Window
from aiogram_dialog.widgets.kbd import Button, Row, Start
from aiogram_dialog.widgets.text import Const, Format

from barber_bot.application.master_actions import MasterActions
from barber_bot.application.ports import Clock
from barber_bot.presentation import flash, texts
from barber_bot.presentation.deps import clock, roles, user_id
from barber_bot.presentation.home import open_home
from barber_bot.presentation.master.day import day_data
from barber_bot.presentation.master.states import (
    DaySchedule,
    Exceptions,
    ManualBooking,
    MasterMenu,
    Services,
    WeeklyHours,
)


async def menu_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, clock: Clock, **_: Any
) -> dict[str, Any]:
    today = clock.now().date()
    count = len(await master_actions.schedule_for(today))
    return {"text": flash.pop_flash(dialog_manager) + texts.master_menu(today, count)}


def _open_day(shift_days: int) -> Any:
    async def on_click(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
        day = clock(manager).now().date() + timedelta(days=shift_days)
        await manager.start(DaySchedule.day, data=day_data(day))

    return on_click


async def on_client_mode(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    roles(manager).set_client_mode(True)
    await open_home(manager, user_id(manager), ShowMode.EDIT)


async def on_master_mode(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    roles(manager).set_client_mode(False)
    await open_home(manager, user_id(manager), ShowMode.EDIT)


master_menu_dialog = Dialog(
    Window(
        Format("{text}"),
        Row(
            Button(Const(texts.BTN_TODAY), id="today", on_click=_open_day(0)),
            Button(Const(texts.BTN_TOMORROW), id="tomorrow", on_click=_open_day(1)),
        ),
        Start(Const(texts.BTN_PICK_DATE), id="pick_date", state=DaySchedule.pick_date),
        Start(Const(texts.BTN_MANUAL_BOOKING), id="manual", state=ManualBooking.name),
        Row(
            Start(Const(texts.BTN_WEEKLY), id="weekly", state=WeeklyHours.week),
            Start(Const(texts.BTN_EXCEPTIONS), id="exceptions", state=Exceptions.list),
        ),
        Start(Const(texts.BTN_MASTER_SERVICES), id="services", state=Services.list),
        Button(Const(texts.BTN_CLIENT_MODE), id="client_mode", on_click=on_client_mode),
        state=MasterMenu.main,
        getter=menu_getter,
    ),
    on_start=flash.on_start,
    on_process_result=flash.on_result,
)
