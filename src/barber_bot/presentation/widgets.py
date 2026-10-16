"""Общие виджеты диалогов."""

from collections.abc import Callable
from datetime import date, timezone
from typing import Any, cast

from aiogram.types import InlineKeyboardButton
from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.kbd import (
    Calendar,
    CalendarConfig,
    CalendarScope,
    CalendarUserConfig,
)
from aiogram_dialog.widgets.kbd.calendar_kbd import CalendarDaysView, CalendarScopeView
from aiogram_dialog.widgets.text import Text

from barber_bot.presentation import texts
from barber_bot.presentation.deps import formatter

# Ключ getter'а со списком дат, на которые можно записаться.
CALENDAR_DATES = "calendar_dates"
UNAVAILABLE_DAY = "·"


class FuncText(Text):
    """Текст, вычисляемый функцией от данных виджета."""

    def __init__(self, func: Callable[[dict[str, Any]], str]) -> None:
        super().__init__()
        self._func = func

    async def _render_text(self, data: dict[str, Any], manager: DialogManager) -> str:
        return self._func(data)


def _day_text(data: dict[str, Any]) -> str:
    day: date = data["date"]
    return str(day.day) if day in data["data"][CALENDAR_DATES] else UNAVAILABLE_DAY


def _month_name(day: date) -> str:
    return texts.MONTHS_FULL[day.month - 1]


class _DaysView(CalendarDaysView):
    """Месяц по-русски, без перехода к выбору месяцев и лет — горизонт всего 30 дней."""

    async def _render_days(
        self,
        config: CalendarConfig,
        offset: date,
        data: dict[str, Any],
        manager: DialogManager,
    ) -> list[list[InlineKeyboardButton]]:
        # Недели целиком вне горизонта рисуются пустыми строками — убираем их.
        rows = await super()._render_days(config, offset, data, manager)
        return [row for row in rows if any(button.text.strip() for button in row)]

    async def _render_pager(
        self,
        config: CalendarConfig,
        offset: date,
        data: dict[str, Any],
        manager: DialogManager,
    ) -> list[InlineKeyboardButton]:
        buttons = await super()._render_pager(config, offset, data, manager)
        prev_button, _zoom, next_button = buttons or (None, None, None)
        return [b for b in (prev_button, next_button) if b is not None]


class AvailableDatesCalendar(Calendar):
    """Календарь, где числами показаны только даты из `CALENDAR_DATES` getter'а.

    Остальные дни — точки; нажатие на них всё равно доходит до `on_click`,
    поэтому обработчик обязан сам проверить, что на дату есть свободные окна.
    """

    def _init_views(self) -> dict[CalendarScope, CalendarScopeView]:
        view = _DaysView(
            self._item_callback_data,
            date_text=FuncText(_day_text),
            today_text=FuncText(_day_text),
            weekday_text=FuncText(lambda data: texts.WEEKDAYS[data["date"].weekday()]),
            header_text=FuncText(lambda data: f"{_month_name(data['date'])} {data['date'].year}"),
            prev_month_text=FuncText(
                lambda data: texts.PREV_MONTH.format(month=_month_name(data["date"]))
            ),
            next_month_text=FuncText(
                lambda data: texts.NEXT_MONTH.format(month=_month_name(data["date"]))
            ),
        )
        # Нажатие на заголовок переключает масштаб — показываем тот же месяц.
        return dict.fromkeys(CalendarScope, view)

    async def _get_user_config(
        self, data: dict[str, Any], manager: DialogManager
    ) -> CalendarUserConfig:
        dates: list[date] = data[CALENDAR_DATES]
        tz = cast(timezone, formatter(manager).tz)  # календарю нужен лишь tzinfo для «сегодня»
        if not dates:
            return CalendarUserConfig(timezone=tz)
        return CalendarUserConfig(timezone=tz, min_date=min(dates), max_date=max(dates))
