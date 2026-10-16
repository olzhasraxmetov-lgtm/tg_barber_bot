"""Регистрация (имя → телефон) и профиль клиента."""

from html import escape
from typing import Any

from aiogram.enums import ContentType
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from aiogram_dialog import Dialog, DialogManager, StartMode, Window
from aiogram_dialog.widgets.input import ManagedTextInput, MessageInput, TextInput
from aiogram_dialog.widgets.kbd import Button, Cancel, RequestContact, SwitchTo
from aiogram_dialog.widgets.markup.reply_keyboard import ReplyKeyboardFactory
from aiogram_dialog.widgets.text import Const, Format

from barber_bot.application.client_actions import ClientActions
from barber_bot.domain.entities import clean_name
from barber_bot.domain.errors import ClientNotRegisteredError
from barber_bot.presentation import flash, texts
from barber_bot.presentation.client.states import ClientMenu, Profile, Registration
from barber_bot.presentation.deps import client_actions, user, user_id

PHONE_KEYBOARD = ReplyKeyboardFactory(
    resize_keyboard=True,
    one_time_keyboard=True,
    input_field_placeholder=Const(texts.PHONE_PLACEHOLDER),
)
PHONE_CONTENT = [ContentType.CONTACT, ContentType.TEXT]


def _tg_name(manager: DialogManager) -> str:
    tg_user = user(manager)
    return " ".join(tg_user.full_name.split()) if tg_user else ""


def _phone_from(message: Message) -> str | None:
    """Телефон из контакта или из текста сообщения. Чужой контакт — None."""
    if message.contact is not None:
        if message.from_user is None or message.contact.user_id != message.from_user.id:
            return None
        return message.contact.phone_number
    return message.text or ""


# --- регистрация ---


async def registration_getter(dialog_manager: DialogManager, **_: Any) -> dict[str, Any]:
    name = _tg_name(dialog_manager)
    return {"tg_name": name, "tg_name_html": escape(name), "has_tg_name": bool(name)}


async def on_accept_tg_name(_: CallbackQuery, __: Button, manager: DialogManager) -> None:
    manager.dialog_data["name"] = _tg_name(manager)
    await manager.switch_to(Registration.phone)


async def on_name_entered(
    _: Message, __: ManagedTextInput[str], manager: DialogManager, name: str
) -> None:
    manager.dialog_data["name"] = name
    await manager.switch_to(Registration.phone)


async def on_registration_phone(message: Message, _: MessageInput, manager: DialogManager) -> None:
    phone = _phone_from(message)
    if phone is None:
        await message.answer(texts.NOT_YOUR_CONTACT)
        return
    client = await client_actions(manager).register(
        user_id(manager), manager.dialog_data["name"], phone
    )
    # Reply-клавиатуру с контактом убираем своим сообщением, иначе aiogram-dialog пришлёт «...».
    await message.answer(
        texts.REGISTERED.format(name=escape(client.name)), reply_markup=ReplyKeyboardRemove()
    )
    await manager.start(ClientMenu.main, mode=StartMode.RESET_STACK)


def _name_input() -> TextInput[str]:
    return TextInput(id="name", type_factory=clean_name, on_success=on_name_entered)


registration_dialog = Dialog(
    Window(
        Const(texts.WELCOME + "\n"),
        Format(texts.ASK_NAME_SUGGESTED, when="has_tg_name"),
        Const(texts.ASK_NAME, when=lambda data, *_: not data["has_tg_name"]),
        Button(
            Format(texts.BTN_YES_NAME),
            id="accept_name",
            on_click=on_accept_tg_name,
            when="has_tg_name",
        ),
        SwitchTo(
            Const(texts.BTN_OTHER_NAME),
            id="other_name",
            state=Registration.enter_name,
            when="has_tg_name",
        ),
        _name_input(),
        state=Registration.name,
        getter=registration_getter,
    ),
    Window(Const(texts.ASK_NAME), _name_input(), state=Registration.enter_name),
    Window(
        Const(texts.ASK_PHONE),
        RequestContact(Const(texts.BTN_SHARE_CONTACT)),
        MessageInput(on_registration_phone, content_types=PHONE_CONTENT),
        markup_factory=PHONE_KEYBOARD,
        state=Registration.phone,
    ),
)


# --- профиль ---


async def profile_getter(
    dialog_manager: DialogManager, client_actions: ClientActions, **_: Any
) -> dict[str, Any]:
    client = await client_actions.get_profile(user_id(dialog_manager))
    if client is None:
        raise ClientNotRegisteredError
    profile = texts.PROFILE.format(name=escape(client.name), phone=texts.format_phone(client.phone))
    return {"text": flash.pop_flash(dialog_manager) + profile}


async def _save_profile(
    manager: DialogManager, *, name: str | None = None, phone: str | None = None
) -> None:
    actions = client_actions(manager)
    me = user_id(manager)
    client = await actions.get_profile(me)
    if client is None:
        raise ClientNotRegisteredError
    await actions.register(me, name or client.name, phone or client.phone)


async def on_new_name(
    message: Message, _: ManagedTextInput[str], manager: DialogManager, name: str
) -> None:
    await _save_profile(manager, name=name)
    flash.set_flash(manager, texts.PROFILE_SAVED)
    await manager.switch_to(Profile.view)


async def on_new_phone(message: Message, _: MessageInput, manager: DialogManager) -> None:
    phone = _phone_from(message)
    if phone is None:
        await message.answer(texts.NOT_YOUR_CONTACT)
        return
    await _save_profile(manager, phone=phone)
    await message.answer(texts.PROFILE_SAVED, reply_markup=ReplyKeyboardRemove())
    await manager.switch_to(Profile.view)


profile_dialog = Dialog(
    Window(
        Format("{text}"),
        SwitchTo(Const(texts.BTN_EDIT_NAME), id="edit_name", state=Profile.edit_name),
        SwitchTo(Const(texts.BTN_EDIT_PHONE), id="edit_phone", state=Profile.edit_phone),
        Cancel(Const(texts.BTN_MENU)),
        state=Profile.view,
        getter=profile_getter,
    ),
    Window(
        Const(texts.ASK_NEW_NAME),
        TextInput(id="new_name", type_factory=clean_name, on_success=on_new_name),
        SwitchTo(Const(texts.BTN_BACK), id="back", state=Profile.view),
        state=Profile.edit_name,
    ),
    Window(
        Const(texts.ASK_NEW_PHONE),
        RequestContact(Const(texts.BTN_SHARE_CONTACT)),
        MessageInput(on_new_phone, content_types=PHONE_CONTENT),
        markup_factory=PHONE_KEYBOARD,
        state=Profile.edit_phone,
    ),
)
