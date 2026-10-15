"""События-уведомления. Как они превращаются в текст и кнопки — забота реализации Notifier."""

from dataclasses import dataclass
from datetime import date, datetime

from barber_bot.domain.entities import Appointment, Client


@dataclass(frozen=True, slots=True)
class AppointmentDetails:
    """Запись вместе с тем, что нужно, чтобы её показать."""

    appointment: Appointment
    client: Client
    service_name: str


# --- мастеру ---


@dataclass(frozen=True, slots=True)
class NewAppointment:
    details: AppointmentDetails


@dataclass(frozen=True, slots=True)
class CancelledByClient:
    details: AppointmentDetails


@dataclass(frozen=True, slots=True)
class Rescheduled:
    details: AppointmentDetails
    old_start: datetime


@dataclass(frozen=True, slots=True)
class VisitConfirmed:
    details: AppointmentDetails


@dataclass(frozen=True, slots=True)
class DailySummary:
    day: date
    appointments: list[AppointmentDetails]


# --- клиенту (только если у клиента есть Telegram) ---


@dataclass(frozen=True, slots=True)
class BookingConfirmation:
    telegram_id: int
    details: AppointmentDetails


@dataclass(frozen=True, slots=True)
class Reminder:
    telegram_id: int
    details: AppointmentDetails


@dataclass(frozen=True, slots=True)
class CancelledByMaster:
    telegram_id: int
    details: AppointmentDetails


Notification = (
    NewAppointment
    | CancelledByClient
    | Rescheduled
    | VisitConfirmed
    | DailySummary
    | BookingConfirmation
    | Reminder
    | CancelledByMaster
)
