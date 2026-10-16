"""Вход в интерфейс клиента: /start и кнопки под уведомлениями (вне диалогов)."""

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager

from barber_bot.application.client_actions import ClientActions
from barber_bot.presentation import keyboards, texts
from barber_bot.presentation.callbacks import (
    AppointmentAction,
    BookAgainCallback,
    ClientAppointmentCallback,
)
from barber_bot.presentation.client.appointments import card_data
from barber_bot.presentation.client.booking import reschedule_data
from barber_bot.presentation.client.states import Booking, MyAppointments
from barber_bot.presentation.home import open_home, open_over_menu

router = Router(name="client")
# Подключается после диалогов: иначе перехватит ввод имени и телефона.
fallback_router = Router(name="client_fallback")


@router.message(CommandStart())
async def on_start(message: Message, dialog_manager: DialogManager) -> None:
    if message.from_user is not None:
        await open_home(dialog_manager, message.from_user.id)


@router.callback_query(
    ClientAppointmentCallback.filter(F.action == AppointmentAction.CONFIRM_VISIT)
)
async def on_confirm_visit(
    callback: CallbackQuery,
    callback_data: ClientAppointmentCallback,
    client_actions: ClientActions,
) -> None:
    details = await client_actions.confirm_visit(
        callback.from_user.id, callback_data.appointment_id
    )
    await callback.answer(texts.VISIT_CONFIRMED_THANKS)
    # «✅ Приду» больше не нужна, «Перенести / Отменить» оставляем.
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=keyboards.client_actions(details, confirm_visit=False)
        )


@router.callback_query(
    ClientAppointmentCallback.filter(F.action != AppointmentAction.CONFIRM_VISIT)
)
async def on_change_appointment(
    callback: CallbackQuery,
    callback_data: ClientAppointmentCallback,
    client_actions: ClientActions,
    dialog_manager: DialogManager,
) -> None:
    appointment_id = callback_data.appointment_id
    # Если менять уже поздно или запись отменена — карточка объяснит, что делать.
    if not await client_actions.can_change(callback.from_user.id, appointment_id):
        await open_over_menu(
            callback, dialog_manager, MyAppointments.card, card_data(appointment_id)
        )
    elif callback_data.action is AppointmentAction.RESCHEDULE:
        await open_over_menu(
            callback, dialog_manager, Booking.date, reschedule_data(appointment_id)
        )
    else:
        await open_over_menu(
            callback, dialog_manager, MyAppointments.cancel, card_data(appointment_id)
        )
    await callback.answer()


@router.callback_query(BookAgainCallback.filter())
async def on_book_again(callback: CallbackQuery, dialog_manager: DialogManager) -> None:
    await open_over_menu(callback, dialog_manager, Booking.service)
    await callback.answer()


@fallback_router.message()
async def on_unexpected_message(message: Message, dialog_manager: DialogManager) -> None:
    """Сообщение вне диалога (например, после перезапуска бота) — показываем меню."""
    if message.from_user is not None:
        await open_home(dialog_manager, message.from_user.id)
