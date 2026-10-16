"""Все тексты бота и форматтеры. Разметка — HTML, пользовательские строки экранируются здесь."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from html import escape

from barber_bot.application.notifications import AppointmentDetails

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
NBSP = " "


def plural(n: int, one: str, few: str, many: str) -> str:
    """plural(1, "запись", "записи", "записей") → «запись»."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def format_date(day: date) -> str:
    """«пн, 19 окт»."""
    return f"{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}"


def format_phone(phone: str) -> str:
    """Нормализованный телефон («77011234567») → «+7 701 123-45-67»."""
    if len(phone) == 11 and phone.startswith("7"):
        return f"+7 {phone[1:4]} {phone[4:7]}-{phone[7:9]}-{phone[9:]}"
    return f"+{phone}"


def format_hours(delta: timedelta) -> str:
    hours = int(delta.total_seconds() // 3600)
    return f"{hours} {plural(hours, 'час', 'часа', 'часов')}"


@dataclass(frozen=True, slots=True)
class Formatter:
    """Форматтеры, которым нужны настройки: пояс мастера и валюта."""

    tz: tzinfo
    currency: str

    def time(self, moment: datetime) -> str:
        return moment.astimezone(self.tz).strftime("%H:%M")

    def date(self, moment: datetime) -> str:
        return format_date(moment.astimezone(self.tz).date())

    def when(self, moment: datetime) -> str:
        """«пн, 19 окт, 14:00»."""
        return f"{self.date(moment)}, {self.time(moment)}"

    def span(self, start: datetime, end: datetime) -> str:
        """«пн, 19 окт, 14:00–15:00»."""
        return f"{self.when(start)}–{self.time(end)}"

    def price(self, amount: int) -> str:
        """«5 000 ₸» с неразрывными пробелами."""
        return f"{amount:,}".replace(",", NBSP) + NBSP + self.currency


# --- кнопки ---

BTN_CONFIRM_VISIT = "✅ Приду"
BTN_RESCHEDULE = "🔁 Перенести"
BTN_CANCEL = "❌ Отменить"
BTN_BOOK_AGAIN = "✂️ Записаться на другое время"
BTN_OPEN_APPOINTMENT = "📋 Открыть запись"


# --- карточка записи ---


def appointment_card(details: AppointmentDetails, fmt: Formatter, *, with_client: bool) -> str:
    a = details.appointment
    lines = []
    if with_client:
        client = details.client
        lines.append(f"👤 {escape(client.name)} · {format_phone(client.phone)}")
    lines.append(f"✂️ {escape(details.service_name)} — {fmt.price(a.price)}")
    lines.append(f"🗓 {fmt.span(a.starts_at, a.ends_at)}")
    return "\n".join(lines)


# --- уведомления мастеру ---


def new_appointment(details: AppointmentDetails, fmt: Formatter) -> str:
    return "🆕 <b>Новая запись</b>\n\n" + appointment_card(details, fmt, with_client=True)


def cancelled_by_client(details: AppointmentDetails, fmt: Formatter) -> str:
    return "❌ <b>Клиент отменил запись</b>\n\n" + appointment_card(details, fmt, with_client=True)


def rescheduled(details: AppointmentDetails, old_start: datetime, fmt: Formatter) -> str:
    return (
        "🔁 <b>Клиент перенёс запись</b>\n\n"
        + appointment_card(details, fmt, with_client=True)
        + f"\n\nБыло: <s>{fmt.when(old_start)}</s>"
    )


def visit_confirmed(details: AppointmentDetails, fmt: Formatter) -> str:
    return "✅ <b>Клиент подтвердил визит</b>\n\n" + appointment_card(
        details, fmt, with_client=True
    )


def daily_summary(day: date, appointments: list[AppointmentDetails], fmt: Formatter) -> str:
    count = len(appointments)
    header = (
        f"☀️ <b>Сводка на {format_date(day)}</b> — "
        f"{count} {plural(count, 'запись', 'записи', 'записей')}"
    )
    rows = []
    for details in sorted(appointments, key=lambda d: d.appointment.starts_at):
        a = details.appointment
        mark = "✅" if a.visit_confirmed else "⏳"
        rows.append(
            f"{mark} {fmt.time(a.starts_at)}–{fmt.time(a.ends_at)} "
            f"{escape(details.service_name)} — {escape(details.client.name)}, "
            f"{format_phone(details.client.phone)}"
        )
    legend = "✅ — визит подтверждён, ⏳ — ещё нет"
    return f"{header}\n\n" + "\n".join(rows) + f"\n\n<i>{legend}</i>"


# --- уведомления клиенту ---


def booking_confirmation(details: AppointmentDetails, fmt: Formatter, min_lead: timedelta) -> str:
    text = "✅ <b>Вы записаны!</b>\n\n" + appointment_card(details, fmt, with_client=False)
    if details.appointment.remind_at is not None:
        text += "\n\nЗа сутки до визита пришлю напоминание."
    return (
        text + f"\nОтменить или перенести запись можно не позднее чем за {format_hours(min_lead)} "
        "до начала."
    )


def reminder(details: AppointmentDetails, fmt: Formatter) -> str:
    return (
        "⏰ <b>Напоминаем о записи</b>\n\n"
        + appointment_card(details, fmt, with_client=False)
        + "\n\nПридёте? Если планы изменились — перенесите или отмените запись."
    )


def cancelled_by_master(details: AppointmentDetails, fmt: Formatter) -> str:
    text = "😔 <b>Мастер отменил вашу запись</b>\n\n" + appointment_card(
        details, fmt, with_client=False
    )
    reason = details.appointment.cancel_reason
    if reason:
        text += f"\n\nПричина: {escape(reason)}"
    return text + "\n\nПриносим извинения. Выберите, пожалуйста, другое время."
