"""Услуги: список со скрытыми, карточка (название, цена, длительность, скрыть/вернуть), добавление.

Добавление проходит те же окна ввода, что и правка: название → цена → длительность.
"""

from html import escape
from typing import Any

from aiogram.types import CallbackQuery, Message
from aiogram_dialog import Dialog, DialogManager, Window
from aiogram_dialog.widgets.input import ManagedTextInput, TextInput
from aiogram_dialog.widgets.kbd import Button, Cancel, Column, Group, Select, SwitchTo
from aiogram_dialog.widgets.text import Const, Format

from barber_bot.application.master_actions import MasterActions
from barber_bot.domain.entities import Service, clean_name
from barber_bot.domain.errors import NotFoundError
from barber_bot.domain.rules import BookingRules
from barber_bot.presentation import flash, texts
from barber_bot.presentation.deps import master_actions
from barber_bot.presentation.master.states import Services
from barber_bot.presentation.texts import Formatter

SERVICE_ID = "service_id"
ADDING = "adding"
DRAFT_NAME = "draft_name"
DRAFT_PRICE = "draft_price"
# Длительности на кнопках: до 4 часов с шагом сетки.
MAX_DURATION_MINUTES = 240


def _adding(manager: DialogManager) -> bool:
    return bool(manager.dialog_data.get(ADDING))


def _service_id(manager: DialogManager) -> int:
    return int(manager.dialog_data[SERVICE_ID])


async def _selected(manager: DialogManager, actions: MasterActions) -> Service:
    service_id = _service_id(manager)
    for service in await actions.list_services():
        if service.id == service_id:
            return service
    raise NotFoundError


async def _update(manager: DialogManager, **changes: Any) -> None:
    await master_actions(manager).update_service(_service_id(manager), **changes)
    flash.set_flash(manager, texts.SERVICE_SAVED)
    await manager.switch_to(Services.card)


def _price(raw: str) -> int:
    """«5 000» или «5000» → 5000; не число — ValueError, его покажет on_price_error."""
    digits = "".join(raw.split())
    if not digits.isdigit():
        raise ValueError(raw)
    return int(digits)


# --- список ---


async def list_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, fmt: Formatter, **_: Any
) -> dict[str, Any]:
    services = await master_actions.list_services()
    return {
        "text": flash.pop_flash(dialog_manager) + texts.master_services_list(services, fmt),
        "services": [
            (s.id, (texts.HIDDEN_MARK if s.is_hidden else "") + texts.service_line(s, fmt))
            for s in services
        ],
    }


async def on_service_selected(
    _: CallbackQuery, __: Any, manager: DialogManager, service_id: int
) -> None:
    manager.dialog_data[SERVICE_ID] = service_id
    manager.dialog_data[ADDING] = False
    await manager.switch_to(Services.card)


async def on_add(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    manager.dialog_data[ADDING] = True
    await manager.switch_to(Services.name)


# --- карточка ---


async def card_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, fmt: Formatter, **_: Any
) -> dict[str, Any]:
    service = await _selected(dialog_manager, master_actions)
    return {
        "text": flash.pop_flash(dialog_manager) + texts.service_card(service, fmt),
        "is_hidden": service.is_hidden,
    }


def _set_hidden(hidden: bool) -> Any:
    async def on_click(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
        await master_actions(manager).update_service(_service_id(manager), is_hidden=hidden)
        flash.set_flash(manager, texts.SERVICE_HIDDEN if hidden else texts.SERVICE_SHOWN)

    return on_click


# --- ввод: название, цена, длительность ---


async def name_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, **_: Any
) -> dict[str, Any]:
    if _adding(dialog_manager):
        return {"text": texts.ASK_SERVICE_NAME, "adding": True}
    service = await _selected(dialog_manager, master_actions)
    return {"text": texts.ASK_NEW_SERVICE_NAME.format(name=escape(service.name)), "adding": False}


async def on_name_entered(
    _: Message, __: ManagedTextInput[str], manager: DialogManager, name: str
) -> None:
    if _adding(manager):
        manager.dialog_data[DRAFT_NAME] = name
        await manager.switch_to(Services.price)
    else:
        await _update(manager, name=name)


async def price_getter(
    dialog_manager: DialogManager, master_actions: MasterActions, **_: Any
) -> dict[str, Any]:
    if _adding(dialog_manager):
        name = escape(dialog_manager.dialog_data[DRAFT_NAME])
        return {"text": texts.ASK_SERVICE_PRICE.format(name=name), "adding": True}
    service = await _selected(dialog_manager, master_actions)
    return {"text": texts.ASK_NEW_PRICE.format(name=escape(service.name)), "adding": False}


async def on_price_entered(
    _: Message, __: ManagedTextInput[int], manager: DialogManager, price: int
) -> None:
    if _adding(manager):
        manager.dialog_data[DRAFT_PRICE] = price
        await manager.switch_to(Services.duration)
    else:
        await _update(manager, price=price)


async def on_price_error(
    message: Message, _: ManagedTextInput[int], __: DialogManager, ___: ValueError
) -> None:
    await message.answer(texts.PRICE_INVALID)


async def duration_getter(
    dialog_manager: DialogManager,
    master_actions: MasterActions,
    fmt: Formatter,
    rules: BookingRules,
    **_: Any,
) -> dict[str, Any]:
    step = rules.grid_step_minutes
    durations = [
        (minutes, texts.format_duration(minutes))
        for minutes in range(step, MAX_DURATION_MINUTES + 1, step)
    ]
    data = dialog_manager.dialog_data
    if _adding(dialog_manager):
        text = texts.ASK_SERVICE_DURATION.format(
            name=escape(data[DRAFT_NAME]), price=fmt.price(data[DRAFT_PRICE])
        )
    else:
        service = await _selected(dialog_manager, master_actions)
        text = texts.ASK_NEW_DURATION.format(name=escape(service.name))
    return {"text": text, "durations": durations, "adding": _adding(dialog_manager)}


async def on_duration_selected(
    _: CallbackQuery, __: Any, manager: DialogManager, minutes: int
) -> None:
    if not _adding(manager):
        await _update(manager, duration_minutes=minutes)
        return
    data = manager.dialog_data
    service = await master_actions(manager).add_service(
        data[DRAFT_NAME], minutes, data[DRAFT_PRICE]
    )
    data.update({SERVICE_ID: service.id, ADDING: False})
    flash.set_flash(manager, texts.SERVICE_ADDED)
    await manager.switch_to(Services.card)


def _back_buttons(add_back_state: Any) -> list[SwitchTo]:
    """При добавлении «← Назад» ведёт на предыдущий шаг, при правке — в карточку."""
    return [
        SwitchTo(Const(texts.BTN_BACK), id="add_back", state=add_back_state, when="adding"),
        SwitchTo(
            Const(texts.BTN_BACK),
            id="edit_back",
            state=Services.card,
            when=lambda data, *_: not data["adding"],
        ),
    ]


services_dialog = Dialog(
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
        Button(Const(texts.BTN_ADD_SERVICE), id="add", on_click=on_add),
        Cancel(Const(texts.BTN_MENU)),
        state=Services.list,
        getter=list_getter,
    ),
    Window(
        Format("{text}"),
        SwitchTo(Const(texts.BTN_EDIT_SERVICE_NAME), id="name", state=Services.name),
        SwitchTo(Const(texts.BTN_EDIT_PRICE), id="price", state=Services.price),
        SwitchTo(Const(texts.BTN_EDIT_DURATION), id="duration", state=Services.duration),
        Button(
            Const(texts.BTN_HIDE),
            id="hide",
            on_click=_set_hidden(True),
            when=lambda data, *_: not data["is_hidden"],
        ),
        Button(Const(texts.BTN_UNHIDE), id="unhide", on_click=_set_hidden(False), when="is_hidden"),
        SwitchTo(Const(texts.BTN_TO_SERVICES), id="to_list", state=Services.list),
        state=Services.card,
        getter=card_getter,
    ),
    Window(
        Format("{text}"),
        TextInput(id="name", type_factory=clean_name, on_success=on_name_entered),
        *_back_buttons(Services.list),
        state=Services.name,
        getter=name_getter,
    ),
    Window(
        Format("{text}"),
        TextInput(
            id="price", type_factory=_price, on_success=on_price_entered, on_error=on_price_error
        ),
        *_back_buttons(Services.name),
        state=Services.price,
        getter=price_getter,
    ),
    Window(
        Format("{text}"),
        Group(
            Select(
                Format("{item[1]}"),
                id="duration",
                item_id_getter=lambda item: item[0],
                items="durations",
                type_factory=int,
                on_click=on_duration_selected,
            ),
            width=4,
        ),
        *_back_buttons(Services.price),
        state=Services.duration,
        getter=duration_getter,
    ),
    on_start=flash.on_start,
)
