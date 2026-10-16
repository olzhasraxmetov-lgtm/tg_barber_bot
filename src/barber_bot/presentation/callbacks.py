"""Кнопки вне диалогов: приходят в сообщениях-уведомлениях, обрабатываются роутерами."""

from enum import StrEnum

from aiogram.filters.callback_data import CallbackData


class AppointmentAction(StrEnum):
    CONFIRM_VISIT = "confirm"
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"


class ClientAppointmentCallback(CallbackData, prefix="appt"):
    """Действие клиента с записью из подтверждения или напоминания."""

    action: AppointmentAction
    appointment_id: int


class BookAgainCallback(CallbackData, prefix="book"):
    """«Записаться на другое время» после отмены мастером."""


class MasterAppointmentCallback(CallbackData, prefix="m_appt"):
    """«Открыть запись» в уведомлении мастеру."""

    appointment_id: int
