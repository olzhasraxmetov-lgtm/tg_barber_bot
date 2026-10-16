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
from barber_bot.presentation.master import handlers as master
from barber_bot.presentation.master.day import day_schedule_dialog
from barber_bot.presentation.master.exceptions import exceptions_dialog
from barber_bot.presentation.master.manual import manual_booking_dialog
from barber_bot.presentation.master.menu import master_menu_dialog
from barber_bot.presentation.master.services import services_dialog
from barber_bot.presentation.master.weekly import weekly_dialog


def setup(dp: Dispatcher, message_manager: MessageManagerProtocol | None = None) -> None:
    """`message_manager` подменяют в тестах диалогов (`MockMessageManager`)."""
    # Порядок важен: /start и кнопки уведомлений раньше диалогов (иначе «/start» уйдёт
    # в поле ввода имени), запасной обработчик сообщений — после них.
    dp.include_routers(
        errors.router,
        client.router,
        master.router,
        registration_dialog,
        profile_dialog,
        menu_dialog,
        booking_dialog,
        my_appointments_dialog,
        master_menu_dialog,
        day_schedule_dialog,
        manual_booking_dialog,
        weekly_dialog,
        exceptions_dialog,
        services_dialog,
        client.fallback_router,
    )
    setup_dialogs(dp, message_manager=message_manager)
