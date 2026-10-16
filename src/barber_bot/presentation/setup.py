"""Подключение интерфейса к диспетчеру: роутеры, диалоги, обработчики ошибок."""

from aiogram import Dispatcher
from aiogram_dialog import setup_dialogs
from aiogram_dialog.api.protocols import MessageManagerProtocol

from barber_bot.presentation import errors
from barber_bot.presentation.client import handlers as client
from barber_bot.presentation.client.appointments import my_appointments_dialog
from barber_bot.presentation.client.booking import booking_dialog
from barber_bot.presentation.client.menu import menu_dialog
from barber_bot.presentation.client.registration import profile_dialog, registration_dialog


def setup(dp: Dispatcher, message_manager: MessageManagerProtocol | None = None) -> None:
    """`message_manager` подменяют в тестах диалогов (`MockMessageManager`)."""
    # Порядок важен: /start и кнопки уведомлений раньше диалогов (иначе «/start» уйдёт
    # в поле ввода имени), запасной обработчик сообщений — после них.
    dp.include_routers(
        errors.router,
        client.router,
        registration_dialog,
        profile_dialog,
        menu_dialog,
        booking_dialog,
        my_appointments_dialog,
        client.fallback_router,
    )
    setup_dialogs(dp, message_manager=message_manager)
