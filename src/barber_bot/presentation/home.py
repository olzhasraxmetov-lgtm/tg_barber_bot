"""Куда вести пользователя: меню мастера, меню клиента или регистрация."""

from contextlib import suppress

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import Data, DialogManager, ShowMode, StartMode

from barber_bot.presentation.client.states import ClientMenu, Registration
from barber_bot.presentation.deps import client_actions, roles
from barber_bot.presentation.master.states import MasterMenu


async def open_home(
    manager: DialogManager, telegram_id: int, show_mode: ShowMode = ShowMode.SEND
) -> None:
    """Главное меню по роли, а если профиля клиента ещё нет — регистрация.
    Старый стек диалогов сбрасывается."""
    if roles(manager).acts_as_master(telegram_id):
        state = MasterMenu.main
    else:
        profile = await client_actions(manager).get_profile(telegram_id)
        state = ClientMenu.main if profile is not None else Registration.name
    await manager.start(state, mode=StartMode.RESET_STACK, show_mode=show_mode)


async def open_over_menu(
    callback: CallbackQuery,
    manager: DialogManager,
    state: State,
    data: Data = None,
    *,
    menu: State = ClientMenu.main,
) -> None:
    """Открыть диалог новым сообщением поверх меню: «🏠 В меню» и «← Назад» вернут в меню."""
    await manager.start(menu, mode=StartMode.RESET_STACK, show_mode=ShowMode.NO_UPDATE)
    await manager.start(state, data=data, show_mode=ShowMode.SEND)
    # aiogram-dialog снимает кнопки с сообщения, из которого пришёл колбэк, а уведомление
    # должно остаться рабочим: передумав переносить, клиент ещё может нажать «✅ Приду».
    message = callback.message
    if isinstance(message, Message) and message.reply_markup is not None:
        with suppress(TelegramBadRequest):  # «message is not modified» — кнопки и так на месте
            await message.edit_reply_markup(reply_markup=message.reply_markup)
