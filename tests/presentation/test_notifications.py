"""Тексты и кнопки уведомлений: кому уходит, что видно, какие кнопки — без сети."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from aiogram.types import InlineKeyboardMarkup

from barber_bot.application.notifications import (
    AppointmentDetails,
    BookingConfirmation,
    CancelledByClient,
    CancelledByMaster,
    DailySummary,
    NewAppointment,
    Notification,
    Reminder,
    Rescheduled,
    VisitConfirmed,
)
from barber_bot.domain.entities import Appointment, Client
from barber_bot.domain.rules import DEFAULT_RULES
from barber_bot.infrastructure.telegram_notifier import NotificationRenderer
from barber_bot.presentation import texts
from barber_bot.presentation.callbacks import (
    AppointmentAction,
    BookAgainCallback,
    ClientAppointmentCallback,
    MasterAppointmentCallback,
)

TZ = ZoneInfo("Asia/Almaty")
MASTER_TG = 1
CLIENT_TG = 111
START = datetime(2026, 10, 19, 14, 0, tzinfo=TZ)  # понедельник

renderer = NotificationRenderer(MASTER_TG, texts.Formatter(TZ, "₸"), DEFAULT_RULES)


def details(
    *,
    starts_at: datetime = START,
    name: str = "Иван",
    remind_at: datetime | None = START - timedelta(days=1),
    reason: str | None = None,
    confirmed: bool = False,
) -> AppointmentDetails:
    appointment = Appointment(
        client_id=1,
        service_id=1,
        starts_at=starts_at,
        duration_minutes=60,
        price=6000,
        remind_at=remind_at,
        cancel_reason=reason,
        visit_confirmed=confirmed,
        id=42,
    )
    client = Client(name=name, phone="77011234567", telegram_id=CLIENT_TG, id=1)
    return AppointmentDetails(appointment, client, "Мужская стрижка")


def callbacks(markup: InlineKeyboardMarkup | None) -> list[str]:
    assert markup is not None
    return [b.callback_data or "" for row in markup.inline_keyboard for b in row]


# --- форматтеры ---


def test_formatter() -> None:
    fmt = texts.Formatter(TZ, "₸")
    assert texts.format_date(date(2026, 10, 19)) == "пн, 19 окт"
    assert fmt.when(START) == "пн, 19 окт, 14:00"
    # Время из базы может прийти в UTC — показываем в поясе мастера.
    assert fmt.time(START.astimezone(UTC)) == "14:00"
    assert fmt.span(START, START + timedelta(hours=1)) == "пн, 19 окт, 14:00–15:00"
    assert fmt.price(6000) == "6 000 ₸"
    assert fmt.price(500) == "500 ₸"


def test_phone_and_plural() -> None:
    assert texts.format_phone("77011234567") == "+7 701 123-45-67"
    assert texts.format_phone("998901234567") == "+998901234567"
    forms = ("запись", "записи", "записей")
    assert [texts.plural(n, *forms) for n in (1, 2, 5, 11, 12, 21, 22, 25)] == [
        "запись",
        "записи",
        "записей",
        "записей",
        "записей",
        "запись",
        "записи",
        "записей",
    ]


# --- получатели ---


@pytest.mark.parametrize(
    ("notification", "chat_id"),
    [
        (NewAppointment(details()), MASTER_TG),
        (CancelledByClient(details()), MASTER_TG),
        (Rescheduled(details(), START - timedelta(hours=2)), MASTER_TG),
        (VisitConfirmed(details()), MASTER_TG),
        (DailySummary(START.date(), [details()]), MASTER_TG),
        (BookingConfirmation(CLIENT_TG, details()), CLIENT_TG),
        (Reminder(CLIENT_TG, details()), CLIENT_TG),
        (CancelledByMaster(CLIENT_TG, details()), CLIENT_TG),
    ],
)
def test_every_notification_goes_to_its_recipient(notification: Notification, chat_id: int) -> None:
    message = renderer.render(notification)
    assert message.chat_id == chat_id
    assert message.text


# --- содержание и кнопки ---


def test_new_appointment_for_master_has_client_and_open_button() -> None:
    message = renderer.render(NewAppointment(details()))
    assert "Иван" in message.text
    assert "+7 701 123-45-67" in message.text
    assert "Мужская стрижка" in message.text
    assert "пн, 19 окт, 14:00–15:00" in message.text
    assert callbacks(message.markup) == [MasterAppointmentCallback(appointment_id=42).pack()]


def test_reschedule_shows_old_time() -> None:
    message = renderer.render(Rescheduled(details(), START - timedelta(hours=2)))
    assert "пн, 19 окт, 12:00" in message.text
    assert "14:00–15:00" in message.text


def test_reminder_buttons() -> None:
    message = renderer.render(Reminder(CLIENT_TG, details()))
    assert callbacks(message.markup) == [
        ClientAppointmentCallback(action=action, appointment_id=42).pack()
        for action in (
            AppointmentAction.CONFIRM_VISIT,
            AppointmentAction.RESCHEDULE,
            AppointmentAction.CANCEL,
        )
    ]
    assert texts.BTN_CONFIRM_VISIT in str(message.markup)


def test_booking_confirmation_offers_cancel_and_reschedule() -> None:
    message = renderer.render(BookingConfirmation(CLIENT_TG, details()))
    actions = [ClientAppointmentCallback.unpack(c).action for c in callbacks(message.markup)]
    assert actions == [AppointmentAction.RESCHEDULE, AppointmentAction.CANCEL]
    assert "напоминание" in message.text
    assert "3 часа" in message.text
    # Клиенту свой телефон не показываем.
    assert "+7 701" not in message.text


def test_booking_confirmation_without_reminder_does_not_promise_it() -> None:
    message = renderer.render(BookingConfirmation(CLIENT_TG, details(remind_at=None)))
    assert "напоминание" not in message.text


def test_cancelled_by_master_with_reason_and_book_again() -> None:
    message = renderer.render(CancelledByMaster(CLIENT_TG, details(reason="заболел")))
    assert "Причина: заболел" in message.text
    assert callbacks(message.markup) == [BookAgainCallback().pack()]

    without_reason = renderer.render(CancelledByMaster(CLIENT_TG, details()))
    assert "Причина" not in without_reason.text


def test_daily_summary_sorted_with_confirmation_marks() -> None:
    late = details(starts_at=START + timedelta(hours=3), name="Пётр", confirmed=True)
    early = details(starts_at=START - timedelta(hours=3), name="Анна")
    text = renderer.render(DailySummary(START.date(), [late, early])).text
    assert "2 записи" in text
    assert text.index("Анна") < text.index("Пётр")
    assert "⏳ 11:00–12:00" in text
    assert "✅ 17:00–18:00" in text


def test_user_input_is_html_escaped() -> None:
    text = renderer.render(NewAppointment(details(name="<b>Хакер</b> & Co"))).text
    assert "&lt;b&gt;Хакер&lt;/b&gt; &amp; Co" in text
    reason = renderer.render(CancelledByMaster(CLIENT_TG, details(reason="<script>"))).text
    assert "&lt;script&gt;" in reason
