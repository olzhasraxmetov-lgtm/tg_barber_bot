"""Сущности домена: клиент, услуга, запись."""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from barber_bot.domain.errors import (
    AppointmentNotActiveError,
    AppointmentNotPastError,
    InvalidDurationError,
    InvalidNameError,
    InvalidPhoneError,
    InvalidPriceError,
    TooLateToChangeError,
)
from barber_bot.domain.rules import BookingRules

NATIONAL_NUMBER_LENGTH = 10


def normalize_phone(raw: str, country_code: str = "7") -> str:
    """Приводит телефон к одному виду — только цифры с кодом страны, — чтобы по нему узнавать
    клиента. Номер без кода страны (10 цифр) получает `country_code`; для кода 7 ведущая «8»
    (8 701 …) заменяется на 7."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == NATIONAL_NUMBER_LENGTH:
        digits = country_code + digits
    elif country_code == "7" and len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if not 11 <= len(digits) <= 15:
        raise InvalidPhoneError(raw)
    return digits


def clean_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise InvalidNameError
    return name


@dataclass(slots=True)
class Client:
    name: str
    phone: str
    telegram_id: int | None = None
    id: int | None = None


@dataclass(slots=True)
class Service:
    name: str
    duration_minutes: int
    price: int
    is_hidden: bool = False
    id: int | None = None

    def validate(self, rules: BookingRules) -> None:
        self.name = clean_name(self.name)
        if self.price < 0:
            raise InvalidPriceError
        step = rules.grid_step_minutes
        if self.duration_minutes <= 0 or self.duration_minutes % step:
            raise InvalidDurationError(f"Длительность должна быть кратна {step} минутам")

    @property
    def duration(self) -> timedelta:
        return timedelta(minutes=self.duration_minutes)


class AppointmentStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"


class CancelledBy(StrEnum):
    CLIENT = "client"
    MASTER = "master"


def reminder_time(starts_at: datetime, now: datetime, rules: BookingRules) -> datetime | None:
    """Когда напомнить о записи; None — напоминание не нужно (до начала меньше суток)."""
    remind_at = starts_at - rules.reminder_before
    return remind_at if remind_at > now else None


@dataclass(slots=True)
class Appointment:
    """Запись. Длительность и цена копируются из услуги в момент записи."""

    client_id: int
    service_id: int
    starts_at: datetime
    duration_minutes: int
    price: int
    is_manual: bool = False
    status: AppointmentStatus = AppointmentStatus.ACTIVE
    cancelled_by: CancelledBy | None = None
    cancel_reason: str | None = None
    visit_confirmed: bool = False
    no_show: bool = False
    remind_at: datetime | None = None
    reminder_sent: bool = False
    id: int | None = None

    @classmethod
    def book(
        cls,
        *,
        client_id: int,
        service: Service,
        starts_at: datetime,
        now: datetime,
        rules: BookingRules,
        is_manual: bool = False,
    ) -> "Appointment":
        return cls(
            client_id=client_id,
            service_id=_require_id(service.id),
            starts_at=starts_at,
            duration_minutes=service.duration_minutes,
            price=service.price,
            is_manual=is_manual,
            remind_at=reminder_time(starts_at, now, rules),
        )

    @property
    def duration(self) -> timedelta:
        return timedelta(minutes=self.duration_minutes)

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + self.duration

    @property
    def is_active(self) -> bool:
        return self.status is AppointmentStatus.ACTIVE

    def client_can_change(self, now: datetime, rules: BookingRules) -> bool:
        return self.is_active and self.starts_at - now >= rules.min_lead

    def ensure_client_can_change(self, now: datetime, rules: BookingRules) -> None:
        self._require_active()
        if not self.client_can_change(now, rules):
            raise TooLateToChangeError

    def cancel_by_client(self, now: datetime, rules: BookingRules) -> None:
        self.ensure_client_can_change(now, rules)
        self.status = AppointmentStatus.CANCELLED
        self.cancelled_by = CancelledBy.CLIENT

    def cancel_by_master(self, reason: str | None = None) -> None:
        self._require_active()
        self.status = AppointmentStatus.CANCELLED
        self.cancelled_by = CancelledBy.MASTER
        self.cancel_reason = reason

    def reschedule(self, new_start: datetime, now: datetime, rules: BookingRules) -> None:
        """Перенос клиентом: та же услуга, новое время, напоминание пересчитывается."""
        self.ensure_client_can_change(now, rules)
        self.starts_at = new_start
        self.remind_at = reminder_time(new_start, now, rules)
        self.reminder_sent = False
        self.visit_confirmed = False

    def confirm_visit(self) -> None:
        self._require_active()
        self.visit_confirmed = True

    def set_no_show(self, value: bool, now: datetime) -> None:
        self._require_active()
        if now < self.starts_at:
            raise AppointmentNotPastError
        self.no_show = value

    def _require_active(self) -> None:
        if not self.is_active:
            raise AppointmentNotActiveError


def _require_id(value: int | None) -> int:
    if value is None:
        raise ValueError("Сущность ещё не сохранена")
    return value
