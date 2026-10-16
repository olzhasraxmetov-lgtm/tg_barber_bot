"""Inline-клавиатуры вне диалогов: под уведомлениями. Нужны и отправителю, и обработчикам кнопок."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from barber_bot.application.notifications import AppointmentDetails
from barber_bot.presentation import texts
from barber_bot.presentation.callbacks import (
    AppointmentAction,
    BookAgainCallback,
    ClientAppointmentCallback,
    MasterAppointmentCallback,
)


def appointment_id(details: AppointmentDetails) -> int:
    value = details.appointment.id
    if value is None:
        raise ValueError("Запись без id")
    return value


def client_actions(details: AppointmentDetails, *, confirm_visit: bool) -> InlineKeyboardMarkup:
    """«✅ Приду» (только в напоминании) и «Перенести / Отменить»."""
    record_id = appointment_id(details)

    def button(text: str, action: AppointmentAction) -> InlineKeyboardButton:
        data = ClientAppointmentCallback(action=action, appointment_id=record_id)
        return InlineKeyboardButton(text=text, callback_data=data.pack())

    rows = []
    if confirm_visit:
        rows.append([button(texts.BTN_CONFIRM_VISIT, AppointmentAction.CONFIRM_VISIT)])
    rows.append(
        [
            button(texts.BTN_RESCHEDULE, AppointmentAction.RESCHEDULE),
            button(texts.BTN_CANCEL, AppointmentAction.CANCEL),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def book_again() -> InlineKeyboardMarkup:
    button = InlineKeyboardButton(
        text=texts.BTN_BOOK_AGAIN, callback_data=BookAgainCallback().pack()
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def open_for_master(details: AppointmentDetails) -> InlineKeyboardMarkup:
    data = MasterAppointmentCallback(appointment_id=appointment_id(details))
    button = InlineKeyboardButton(text=texts.BTN_OPEN_APPOINTMENT, callback_data=data.pack())
    return InlineKeyboardMarkup(inline_keyboard=[[button]])
