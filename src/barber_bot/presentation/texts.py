"""Все тексты бота и форматтеры. Разметка — HTML, пользовательские строки экранируются здесь."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from html import escape

from barber_bot.application.notifications import AppointmentDetails
from barber_bot.domain.entities import CancelledBy, Service
from barber_bot.domain.errors import (
    AppointmentNotActiveError,
    AppointmentNotPastError,
    ClientNotRegisteredError,
    DomainError,
    InvalidDurationError,
    InvalidNameError,
    InvalidPhoneError,
    InvalidPriceError,
    InvalidWorkingHoursError,
    NotFoundError,
    PhoneTakenError,
    ServiceHiddenError,
    TooLateToChangeError,
    WindowTakenError,
    WindowUnavailableError,
)
from barber_bot.domain.schedule import ScheduleException, WorkingHours

WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
MONTHS_FULL = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)  # fmt: skip
WEEKDAYS_FULL = (
    "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье",
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
    return f"{header}\n\n" + schedule_rows(appointments, fmt) + f"\n\n<i>{SCHEDULE_LEGEND}</i>"


SCHEDULE_LEGEND = "✅ — визит подтверждён, ⏳ — ещё нет"


def schedule_mark(details: AppointmentDetails) -> str:
    a = details.appointment
    if a.no_show:
        return "🚷"
    return "✅" if a.visit_confirmed else "⏳"


def schedule_rows(appointments: list[AppointmentDetails], fmt: Formatter) -> str:
    """Записи дня по времени: «✅ 14:00–15:00 Стрижка — Иван, +7 701 123-45-67»."""
    rows = []
    for details in sorted(appointments, key=lambda d: d.appointment.starts_at):
        a = details.appointment
        rows.append(
            f"{schedule_mark(details)} {fmt.time(a.starts_at)}–{fmt.time(a.ends_at)} "
            f"{escape(details.service_name)} — {escape(details.client.name)}, "
            f"{format_phone(details.client.phone)}"
        )
    return "\n".join(rows)


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


# --- интерфейс мастера ---

BTN_TODAY = "📅 Сегодня"
BTN_TOMORROW = "📅 Завтра"
BTN_PICK_DATE = "🗓 Другая дата"
BTN_MANUAL_BOOKING = "➕ Записать клиента"
BTN_WEEKLY = "🕐 График"
BTN_EXCEPTIONS = "🚫 Исключения"
BTN_MASTER_SERVICES = "💈 Услуги"
BTN_CLIENT_MODE = "👤 Режим клиента"
BTN_MASTER_MODE = "✂️ Режим мастера"
BTN_PREV_DAY = "◀ {prev_day}"
BTN_NEXT_DAY = "{next_day} ▶"
BTN_TO_SCHEDULE = "← К расписанию"
BTN_NO_SHOW = "🚷 Отметить неявку"
BTN_UNDO_NO_SHOW = "↩️ Снять неявку"
BTN_CANCEL_NO_REASON = "Отменить без причины"
BTN_START_TIME = "Начало: {start}"
BTN_END_TIME = "Конец: {end}"
BTN_DAY_OFF = "🚫 Сделать выходным"
BTN_WORKDAY = "✅ Сделать рабочим"
BTN_SAVE = "💾 Сохранить"
BTN_ADD_EXCEPTION = "➕ Добавить исключение"
BTN_DELETE = "🗑 Удалить"
BTN_ONE_DAY = "Только {date_from}"
BTN_CLOSED = "🚫 Закрыто весь день"
BTN_CHANGED_HOURS = "🕐 Другие часы"
BTN_CANCEL_CONFLICTS = "Отменить их и сохранить"
BTN_DONT_SAVE = "Не сохранять"
BTN_ADD_SERVICE = "➕ Добавить услугу"
BTN_EDIT_SERVICE_NAME = "✏️ Название"
BTN_EDIT_PRICE = "💰 Цена"
BTN_EDIT_DURATION = "⏱ Длительность"
BTN_HIDE = "🙈 Скрыть"
BTN_UNHIDE = "👁 Вернуть в прайс"
BTN_TO_SERVICES = "← К услугам"

MASTER_MENU = "✂️ <b>Меню мастера</b>\n\nСегодня, {date}: {summary}."

# расписание и карточка записи
PICK_SCHEDULE_DATE = "🗓 <b>Расписание</b>\n\nВыберите дату:"
CANCEL_REASON_TOO_LONG = "Слишком длинная причина — уложитесь в {limit} символов."
ASK_MASTER_CANCEL = (
    "Отменить запись?\n\n{card}\n\n"
    "Напишите причину одним сообщением — клиент её увидит. "
    "Или нажмите «Отменить без причины»."
)
NO_TELEGRAM_WARNING = "⚠️ У клиента нет Telegram — уведомление не придёт, предупредите его сами."
MASTER_CANCELLED = "Запись отменена."
CLIENT_NOTIFIED = " Клиент получил уведомление."
NO_SHOW_SET = "Отмечена неявка."
NO_SHOW_CLEARED = "Неявка снята."

# ручная запись
MANUAL_HEADER = "➕ <b>Ручная запись</b>"
MANUAL_ASK_NAME = MANUAL_HEADER + "\n\nКак зовут клиента?"
MANUAL_ASK_PHONE = MANUAL_HEADER + "\n👤 {name}\n\nТелефон клиента:"
MANUAL_CHOOSE_SERVICE = MANUAL_HEADER + "\n👤 {name}\n\nВыберите услугу:"
CONFIRM_MANUAL = (
    "Записать клиента?\n\n{card}\n\n"
    "Если клиент с этим телефоном уже есть, запись привяжется к нему."
)
MANUAL_BOOKED = "✅ Клиент записан."
MANUAL_BOOKED_NOTIFIED = "✅ Клиент записан — подтверждение ушло ему в Telegram."

# график
WEEKLY = (
    "🕐 <b>График</b>\n\n{rows}\n\n"
    "Обед {lunch} действует в каждый рабочий день, настраивать его не нужно.\n"
    "Выберите день, чтобы изменить часы:"
)
WEEKLY_DAY = "🕐 <b>{weekday}</b>\n\n{hours}\n\nИзмените часы и нажмите «💾 Сохранить»."
DAY_OFF = "выходной"
PICK_START = "Во сколько начинается рабочий день?"
PICK_END = "Во сколько заканчивается?"
WEEKLY_SAVED = "График сохранён."
CONFLICTS = (
    "⚠️ <b>Эти записи не помещаются в новые часы</b>\n\n{rows}\n\n"
    "Отменить их и уведомить клиентов? Иначе изменение не сохранится."
)
NOT_SAVED = "Изменения не сохранены."
CONFLICTS_CANCELLED = " Отменено записей: {count}."

# исключения
EXCEPTIONS_HEADER = "🚫 <b>Исключения</b>"
EXCEPTIONS = EXCEPTIONS_HEADER + "\n\n{rows}\n\nВыберите исключение, чтобы удалить его."
NO_EXCEPTIONS = (
    EXCEPTIONS_HEADER + "\n\nБудущих исключений нет. Исключение закрывает дни (отпуск, болезнь) "
    "или меняет часы на конкретные даты, не трогая график."
)
EXCEPTION_CARD = (
    EXCEPTIONS_HEADER + "\n\n{line}\n\nУдалить его? В эти дни снова будет действовать график."
)
NEW_EXCEPTION = "🚫 <b>Новое исключение</b>"
EXC_PICK_FROM = NEW_EXCEPTION + "\n\nС какой даты?"
EXC_PICK_TO = NEW_EXCEPTION + "\n\nС {date_from} по какую дату?"
EXC_KIND = NEW_EXCEPTION + "\n🗓 {period}\n\nЧто в эти дни?"
EXC_PICK_START = NEW_EXCEPTION + "\n🗓 {period}\n\n" + PICK_START
EXC_PICK_END = NEW_EXCEPTION + "\n🗓 {period}\n\n" + PICK_END
EXCEPTION_ADDED = "Исключение добавлено."
EXCEPTION_DELETED = "Исключение удалено."
EXCEPTION_CLOSED = "закрыто"

# услуги
MASTER_SERVICES = "💈 <b>Услуги</b>\n\n{rows}\n\nВыберите услугу, чтобы изменить её."
NO_MASTER_SERVICES = "💈 <b>Услуги</b>\n\nУслуг пока нет — добавьте первую."
HIDDEN_MARK = "🙈 "
SERVICE_CARD = (
    "💈 <b>{name}</b>\n\nДлительность: {duration}\nЦена: {price}{hidden}\n\n"
    "<i>Новые цена и длительность действуют для новых записей.</i>"
)
SERVICE_HIDDEN_NOTE = "\n\n🙈 Скрыта: клиенты её не видят, существующие записи сохраняются."
NEW_SERVICE = "💈 <b>Новая услуга</b>"
ASK_SERVICE_NAME = NEW_SERVICE + "\n\nНазвание:"
ASK_SERVICE_PRICE = NEW_SERVICE + "\n{name}\n\nЦена — целым числом, например 5000:"
ASK_SERVICE_DURATION = NEW_SERVICE + "\n{name} · {price}\n\nДлительность:"
ASK_NEW_SERVICE_NAME = "💈 <b>{name}</b>\n\nНовое название:"
ASK_NEW_PRICE = "💈 <b>{name}</b>\n\nНовая цена — целым числом, например 5000:"
ASK_NEW_DURATION = "💈 <b>{name}</b>\n\nНовая длительность:"
PRICE_INVALID = "Введите цену целым числом, например 5000."
SERVICE_ADDED = "Услуга добавлена."
SERVICE_SAVED = "Сохранено."
SERVICE_HIDDEN = "Услуга скрыта — клиенты её больше не видят."
SERVICE_SHOWN = "Услуга снова в прайсе."


def master_menu(day: date, count: int) -> str:
    summary = f"{count} {plural(count, 'запись', 'записи', 'записей')}" if count else "записей нет"
    return MASTER_MENU.format(date=format_date(day), summary=summary)


def day_schedule(day: date, appointments: list[AppointmentDetails], fmt: Formatter) -> str:
    header = f"📅 <b>Расписание на {format_date(day)}</b>"
    if not appointments:
        return header + "\n\nЗаписей нет."
    count = len(appointments)
    return (
        f"{header} — {count} {plural(count, 'запись', 'записи', 'записей')}\n\n"
        + schedule_rows(appointments, fmt)
        + f"\n\n<i>{SCHEDULE_LEGEND}, 🚷 — неявка. Нажмите на запись, чтобы открыть её.</i>"
    )


def schedule_button(details: AppointmentDetails, fmt: Formatter) -> str:
    """«⏳ 14:00 Иван» — без разметки."""
    start = fmt.time(details.appointment.starts_at)
    return f"{schedule_mark(details)} {start} {details.client.name}"


def master_card(details: AppointmentDetails, fmt: Formatter) -> str:
    a = details.appointment
    notes = []
    if a.is_manual:
        notes.append("✍️ Ручная запись")
    if not a.is_active:
        who = "клиентом" if a.cancelled_by is CancelledBy.CLIENT else "мастером"
        notes.append(f"❌ Отменена {who}")
        if a.cancel_reason:
            notes.append(f"Причина: {escape(a.cancel_reason)}")
    elif a.no_show:
        notes.append("🚷 Неявка")
    elif a.visit_confirmed:
        notes.append("✅ Клиент подтвердил визит")
    card = appointment_card(details, fmt, with_client=True)
    return card + "\n\n" + "\n".join(notes) if notes else card


def manual_header(name: str, service_name: str) -> str:
    return f"{MANUAL_HEADER}\n👤 {escape(name)}\n{header_for(service_name)}"


def format_hours_span(hours: WorkingHours) -> str:
    return f"{hours.start:%H:%M}–{hours.end:%H:%M}"


def weekly(days: dict[int, WorkingHours], lunch: WorkingHours) -> str:
    rows = [
        f"{name} — {format_hours_span(days[weekday]) if weekday in days else DAY_OFF}"
        for weekday, name in enumerate(WEEKDAYS_FULL)
    ]
    return WEEKLY.format(rows="\n".join(rows), lunch=format_hours_span(lunch))


def weekday_button(weekday: int, hours: WorkingHours | None) -> str:
    return f"{WEEKDAYS[weekday].capitalize()} · {format_hours_span(hours) if hours else DAY_OFF}"


def format_period(date_from: date, date_to: date) -> str:
    if date_from == date_to:
        return format_date(date_from)
    return f"{format_date(date_from)} – {format_date(date_to)}"


def exception_line(exception: ScheduleException) -> str:
    """«пн, 19 окт – пт, 23 окт · закрыто» — без разметки."""
    period = format_period(exception.date_from, exception.date_to)
    hours = format_hours_span(exception.hours) if exception.hours else EXCEPTION_CLOSED
    return f"{period} · {hours}"


def conflicts(appointments: list[AppointmentDetails], fmt: Formatter) -> str:
    rows = [
        f"• {fmt.when(d.appointment.starts_at)} {escape(d.service_name)} — "
        f"{escape(d.client.name)}, {format_phone(d.client.phone)}"
        for d in sorted(appointments, key=lambda d: d.appointment.starts_at)
    ]
    return CONFLICTS.format(rows="\n".join(rows))


def master_services_list(services: list[Service], fmt: Formatter) -> str:
    if not services:
        return NO_MASTER_SERVICES
    rows = [
        f"• {HIDDEN_MARK if s.is_hidden else ''}<b>{escape(s.name)}</b> — "
        f"{format_duration(s.duration_minutes)}, {fmt.price(s.price)}"
        for s in services
    ]
    return MASTER_SERVICES.format(rows="\n".join(rows))


def service_card(service: Service, fmt: Formatter) -> str:
    return SERVICE_CARD.format(
        name=escape(service.name),
        duration=format_duration(service.duration_minutes),
        price=fmt.price(service.price),
        hidden=SERVICE_HIDDEN_NOTE if service.is_hidden else "",
    )


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
    NotFoundError: "Не найдено — возможно, уже удалено.",
    InvalidWorkingHoursError: "Начало рабочего дня должно быть раньше конца.",
    InvalidDurationError: "Длительность должна быть кратна 30 минутам.",
    InvalidPriceError: "Цена не может быть отрицательной.",
}
UNKNOWN_ERROR = "Что-то пошло не так. Попробуйте ещё раз или нажмите /start."


def error_text(error: DomainError) -> str:
    for kind in type(error).__mro__:
        if kind in ERRORS:
            return ERRORS[kind]
    return UNKNOWN_ERROR
