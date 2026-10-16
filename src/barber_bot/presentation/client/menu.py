"""Главное меню клиента и прайс."""

from html import escape
from typing import Any

from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.kbd import Start, SwitchTo
from aiogram_dialog.widgets.text import Const, Format

from barber_bot.application.client_actions import ClientActions
from barber_bot.domain.errors import ClientNotRegisteredError
from barber_bot.presentation import flash, texts
from barber_bot.presentation.client.states import Booking, ClientMenu, MyAppointments, Profile
from barber_bot.presentation.deps import user_id
from barber_bot.presentation.texts import Formatter


async def menu_getter(
    dialog_manager: DialogManager, client_actions: ClientActions, **_: Any
) -> dict[str, Any]:
    client = await client_actions.get_profile(user_id(dialog_manager))
    if client is None:
        raise ClientNotRegisteredError
    menu = texts.MENU.format(name=escape(client.name))
    return {"text": flash.pop_flash(dialog_manager) + menu}


async def services_getter(
    client_actions: ClientActions, fmt: Formatter, **_: Any
) -> dict[str, Any]:
    services = await client_actions.list_services()
    return {"text": texts.services_list(services, fmt), "has_services": bool(services)}


menu_dialog = Dialog(
    Window(
        Format("{text}"),
        Start(Const(texts.BTN_BOOK), id="book", state=Booking.service),
        Start(Const(texts.BTN_MY_APPOINTMENTS), id="my", state=MyAppointments.list),
        SwitchTo(Const(texts.BTN_SERVICES), id="services", state=ClientMenu.services),
        Start(Const(texts.BTN_PROFILE), id="profile", state=Profile.view),
        state=ClientMenu.main,
        getter=menu_getter,
    ),
    Window(
        Format("{text}"),
        Start(Const(texts.BTN_BOOK), id="book", state=Booking.service, when="has_services"),
        SwitchTo(Const(texts.BTN_BACK), id="back", state=ClientMenu.main),
        state=ClientMenu.services,
        getter=services_getter,
    ),
    on_start=flash.on_start,
    on_process_result=flash.on_result,
)
