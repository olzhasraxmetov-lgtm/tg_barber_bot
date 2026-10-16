"""Кнопки мастера вне диалогов: «📋 Открыть запись» в уведомлении."""

from aiogram import Router
from aiogram.types import CallbackQuery
from aiogram_dialog import DialogManager

from barber_bot.presentation.callbacks import MasterAppointmentCallback
from barber_bot.presentation.home import open_over_menu
from barber_bot.presentation.master.day import card_data
from barber_bot.presentation.master.states import DaySchedule, MasterMenu
from barber_bot.presentation.roles import Roles

router = Router(name="master")


@router.callback_query(MasterAppointmentCallback.filter())
async def on_open_appointment(
    callback: CallbackQuery,
    callback_data: MasterAppointmentCallback,
    dialog_manager: DialogManager,
    roles: Roles,
) -> None:
    if not roles.is_master(callback.from_user.id):
        await callback.answer()
        return
    # Кнопка из уведомления мастеру — значит, дальше он работает как мастер.
    roles.set_client_mode(False)
    await open_over_menu(
        callback,
        dialog_manager,
        DaySchedule.card,
        card_data(callback_data.appointment_id),
        menu=MasterMenu.main,
    )
    await callback.answer()
