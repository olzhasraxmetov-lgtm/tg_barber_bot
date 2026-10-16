"""Все тексты бота и форматтеры. Разметка — HTML, пользовательские строки экранируются здесь."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from html import escape

from barber_bot.application.notifications import AppointmentDetails
from barber_bot.domain.entities import Service
from barber_bot.domain.errors import (
    AppointmentNotActiveError,
    AppointmentNotPastError,
    ClientNotRegisteredError,
    DomainError,
    InvalidNameError,
    InvalidPhoneError,
    NotFoundError,
    PhoneTakenError,
    ServiceHiddenError,
    TooLateToChangeError,
    WindowTakenError,
    WindowUnavailableError,
)

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
MONTHS_FULL = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)  # fmt: skip
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


# --- интерфейс клиента ---


def format_duration(minutes: int) -> str:
    """90 → «1 ч 30 мин»."""
    hours, rest = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours}{NBSP}ч")
    if rest or not hours:
        parts.append(f"{rest}{NBSP}мин")
    return " ".join(parts)


def service_line(service: Service, fmt: Formatter) -> str:
    """«Мужская стрижка · 1 ч · 5 000 ₸» — для кнопок, без разметки."""
    duration = format_duration(service.duration_minutes)
    return f"{service.name} · {duration} · {fmt.price(service.price)}"


def appointment_button(details: AppointmentDetails, fmt: Formatter) -> str:
    """«пн, 19 окт, 14:00 · Мужская стрижка»."""
    return f"{fmt.when(details.appointment.starts_at)} · {details.service_name}"


BTN_YES_NAME = "✅ Да, {tg_name}"
BTN_OTHER_NAME = "✏️ Другое имя"
BTN_SHARE_CONTACT = "📱 Поделиться контактом"
BTN_BOOK = "✂️ Записаться"
BTN_MY_APPOINTMENTS = "📅 Мои записи"
BTN_SERVICES = "💈 Услуги и цены"
BTN_PROFILE = "👤 Профиль"
BTN_EDIT_NAME = "✏️ Изменить имя"
BTN_EDIT_PHONE = "📱 Изменить телефон"
BTN_CONFIRM = "✅ Подтвердить"
BTN_BACK = "← Назад"
BTN_MENU = "🏠 В меню"
BTN_TO_LIST = "← К записям"
BTN_YES_CANCEL = "Да, отменить"
BTN_NO_KEEP = "← Нет, оставить"
PREV_MONTH = "← {month}"
NEXT_MONTH = "{month} →"

WELCOME = (
    "👋 <b>Здравствуйте!</b>\n\n"
    "Я бот онлайн-записи к мастеру. Здесь можно выбрать услугу и свободное время, "
    "а потом перенести или отменить запись. За сутки до визита я пришлю напоминание.\n\n"
    "Сначала познакомимся — это нужно один раз."
)
ASK_NAME_SUGGESTED = "Записать вас как <b>{tg_name_html}</b>?"
ASK_NAME = "Как к вам обращаться? Напишите имя."
ASK_PHONE = (
    "Теперь телефон — по нему мастер свяжется, если что-то изменится.\n\n"
    "Нажмите «📱 Поделиться контактом» внизу или напишите номер сообщением."
)
ASK_NEW_NAME = "Напишите новое имя."
ASK_NEW_PHONE = "Нажмите «📱 Поделиться контактом» внизу или напишите новый номер сообщением."
PHONE_PLACEHOLDER = "+7 701 123-45-67"
NOT_YOUR_CONTACT = "Это чужой контакт. Поделитесь, пожалуйста, своим или напишите номер."
REGISTERED = "Готово, {name}! Теперь можно записаться."
PROFILE_SAVED = "Сохранено."

MENU = "💈 <b>Главное меню</b>\n\nЧто сделаем, {name}?"
NO_SERVICES = "Пока нет доступных услуг — загляните позже."
SERVICES_HEADER = "💈 <b>Услуги и цены</b>"
PROFILE = "👤 <b>Профиль</b>\n\nИмя: {name}\nТелефон: {phone}"

CHOOSE_SERVICE = "✂️ <b>Запись</b>\n\nВыберите услугу:"
CHOOSE_DATE = "{header}\n\nВыберите дату — доступны только дни со свободным временем:"
NO_DATES = "{header}\n\nВ ближайшие {days} дней свободного времени нет. Загляните позже."
CHOOSE_TIME = "{header}\n🗓 {date}\n\nВыберите время:"
NO_TIMES = "{header}\n🗓 {date}\n\nНа эту дату свободного времени не осталось — выберите другую."
DATE_UNAVAILABLE = "На эту дату записаться нельзя — выберите отмеченную числом."
CONFIRM_BOOKING = "Проверьте, всё верно?\n\n{card}"
CONFIRM_RESCHEDULE = "Перенести запись?\n\n{card}\n\nБыло: <s>{old}</s>"
WINDOW_TAKEN = "⚠️ Это время только что заняли — выберите другое."
WINDOW_UNAVAILABLE = (
    "⚠️ Это время уже недоступно: записаться можно не позднее чем за {lead} до начала. "
    "Выберите другое."
)
BOOKED = "✅ Вы записаны — подробности в сообщении выше."
RESCHEDULED = "✅ Запись перенесена."

NO_APPOINTMENTS = "📅 У вас нет предстоящих записей."
MY_APPOINTMENTS = "📅 <b>Мои записи</b>\n\nВыберите запись:"
ASK_CANCEL = "Отменить запись?\n\n{card}"
CANCELLED = "Запись отменена."
APPOINTMENT_CANCELLED = "❌ Эта запись отменена."
APPOINTMENT_PAST = "Эта запись уже прошла."
CONTACT_MASTER = (
    "До начала меньше {lead} — отменить или перенести запись в боте уже нельзя. "
    "Для отмены свяжитесь с мастером."
)
VISIT_CONFIRMED_THANKS = "Спасибо! Мастер знает, что вы придёте."
STALE_MENU = "Это меню устарело — вот актуальное."


def preview_card(
    service_name: str, price: int, start: datetime, duration_minutes: int, fmt: Formatter
) -> str:
    """Карточка ещё не созданной записи — для экрана подтверждения."""
    end = start + timedelta(minutes=duration_minutes)
    return f"✂️ {escape(service_name)} — {fmt.price(price)}\n🗓 {fmt.span(start, end)}"


def header_for(service_name: str) -> str:
    return f"✂️ <b>{escape(service_name)}</b>"


def services_list(services: list[Service], fmt: Formatter) -> str:
    if not services:
        return NO_SERVICES
    rows = [
        f"• <b>{escape(s.name)}</b> — {format_duration(s.duration_minutes)}, {fmt.price(s.price)}"
        for s in services
    ]
    return SERVICES_HEADER + "\n\n" + "\n".join(rows)


# --- ошибки ---

ERRORS: dict[type[DomainError], str] = {
    WindowTakenError: WINDOW_TAKEN,
    WindowUnavailableError: "⚠️ Это время уже недоступно. Выберите другое.",
    TooLateToChangeError: "До начала слишком мало времени — для отмены свяжитесь с мастером.",
    ServiceHiddenError: "Эта услуга больше недоступна — выберите другую.",
    InvalidPhoneError: "Не похоже на номер телефона. Пример: +7 701 123-45-67.",
    InvalidNameError: "Имя не может быть пустым.",
    PhoneTakenError: "Этот номер уже привязан к другому аккаунту Telegram.",
    ClientNotRegisteredError: "Сначала познакомимся — нажмите /start.",
    AppointmentNotActiveError: "Эта запись уже отменена.",
    AppointmentNotPastError: "Запись ещё не началась.",
    NotFoundError: "Запись не найдена.",
}
UNKNOWN_ERROR = "Что-то пошло не так. Попробуйте ещё раз или нажмите /start."


def error_text(error: DomainError) -> str:
    for kind in type(error).__mro__:
        if kind in ERRORS:
            return ERRORS[kind]
    return UNKNOWN_ERROR
