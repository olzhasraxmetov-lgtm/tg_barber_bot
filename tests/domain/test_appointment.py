from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from barber_bot.domain.entities import (
    Appointment,
    AppointmentStatus,
    CancelledBy,
    Service,
    clean_name,
    normalize_phone,
)
from barber_bot.domain.errors import (
    AppointmentNotActiveError,
    AppointmentNotPastError,
    InvalidDurationError,
    InvalidNameError,
    InvalidPhoneError,
    InvalidPriceError,
    InvalidWorkingHoursError,
    TooLateToChangeError,
)
from barber_bot.domain.rules import DEFAULT_RULES
from barber_bot.domain.schedule import WorkingHours

TZ = ZoneInfo("Asia/Almaty")
START = datetime(2026, 10, 20, 15, 0, tzinfo=TZ)
HAIRCUT = Service("Стрижка", 60, 5000, id=1)


def book(now: datetime, starts_at: datetime = START) -> Appointment:
    return Appointment.book(
        client_id=1, service=HAIRCUT, starts_at=starts_at, now=now, rules=DEFAULT_RULES
    )


def test_booking_copies_duration_and_price_from_service() -> None:
    appt = book(START - timedelta(days=2))
    assert (appt.duration_minutes, appt.price) == (60, 5000)
    assert appt.ends_at == START + timedelta(hours=1)


def test_reminder_is_scheduled_24_hours_before() -> None:
    assert book(START - timedelta(days=2)).remind_at == START - timedelta(hours=24)


def test_no_reminder_when_booked_less_than_24_hours_before() -> None:
    assert book(START - timedelta(hours=20)).remind_at is None


@pytest.mark.parametrize(
    ("before_start", "allowed"),
    [(timedelta(hours=3), True), (timedelta(hours=2, minutes=59), False)],
)
def test_client_cancel_allowed_up_to_exactly_three_hours(
    before_start: timedelta, allowed: bool
) -> None:
    appt = book(START - timedelta(days=2))
    now = START - before_start
    if allowed:
        appt.cancel_by_client(now, DEFAULT_RULES)
        assert appt.status is AppointmentStatus.CANCELLED
        assert appt.cancelled_by is CancelledBy.CLIENT
    else:
        with pytest.raises(TooLateToChangeError):
            appt.cancel_by_client(now, DEFAULT_RULES)


def test_master_can_cancel_any_time_with_reason() -> None:
    appt = book(START - timedelta(days=2))
    appt.cancel_by_master("Заболел")
    assert appt.cancelled_by is CancelledBy.MASTER
    assert appt.cancel_reason == "Заболел"


def test_cancelled_appointment_cannot_be_cancelled_again() -> None:
    appt = book(START - timedelta(days=2))
    appt.cancel_by_master()
    with pytest.raises(AppointmentNotActiveError):
        appt.cancel_by_master()


def test_reschedule_recalculates_reminder_and_resets_flags() -> None:
    now = START - timedelta(days=2)
    appt = book(now)
    appt.reminder_sent = True
    appt.visit_confirmed = True
    new_start = START + timedelta(days=3)
    appt.reschedule(new_start, now, DEFAULT_RULES)
    assert appt.starts_at == new_start
    assert appt.remind_at == new_start - timedelta(hours=24)
    assert not appt.reminder_sent
    assert not appt.visit_confirmed
    assert (appt.duration_minutes, appt.service_id) == (60, 1)


def test_reschedule_too_late_is_rejected() -> None:
    appt = book(START - timedelta(days=2))
    with pytest.raises(TooLateToChangeError):
        appt.reschedule(START + timedelta(days=1), START - timedelta(hours=1), DEFAULT_RULES)


def test_no_show_only_after_start_and_can_be_reverted() -> None:
    appt = book(START - timedelta(days=2))
    with pytest.raises(AppointmentNotPastError):
        appt.set_no_show(True, START - timedelta(minutes=1))
    appt.set_no_show(True, START + timedelta(hours=1))
    assert appt.no_show
    appt.set_no_show(False, START + timedelta(hours=2))
    assert not appt.no_show


@pytest.mark.parametrize("minutes", [0, 45, 100])
def test_service_duration_must_be_multiple_of_30(minutes: int) -> None:
    with pytest.raises(InvalidDurationError):
        Service("X", minutes, 100).validate(DEFAULT_RULES)


def test_working_hours_must_be_aligned_and_ordered() -> None:
    with pytest.raises(InvalidWorkingHoursError):
        WorkingHours(time(10, 15), time(18)).validate(DEFAULT_RULES)
    with pytest.raises(InvalidWorkingHoursError):
        WorkingHours(time(18), time(10)).validate(DEFAULT_RULES)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("+7 (701) 123-45-67", "77011234567"), ("87011234567", "77011234567")],
)
def test_phone_is_normalized(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


def test_garbage_phone_is_rejected() -> None:
    with pytest.raises(InvalidPhoneError):
        normalize_phone("12-34")


def test_phone_without_country_code_gets_default_code() -> None:
    assert normalize_phone("701 555 55 55") == "77015555555"
    assert normalize_phone("701 555 55 55", country_code="998") == "9987015555555"


def test_leading_eight_is_only_replaced_for_code_7() -> None:
    assert normalize_phone("8 701 555 55 55") == "77015555555"
    assert normalize_phone("80291234567", country_code="375") == "80291234567"


@pytest.mark.parametrize("name", ["", "   "])
def test_empty_names_are_rejected(name: str) -> None:
    with pytest.raises(InvalidNameError):
        clean_name(name)
    with pytest.raises(InvalidNameError):
        Service(name, 30, 100).validate(DEFAULT_RULES)


def test_name_whitespace_is_collapsed() -> None:
    assert clean_name("  Иван   Петров ") == "Иван Петров"


def test_negative_price_is_rejected() -> None:
    with pytest.raises(InvalidPriceError):
        Service("Стрижка", 30, -1).validate(DEFAULT_RULES)
