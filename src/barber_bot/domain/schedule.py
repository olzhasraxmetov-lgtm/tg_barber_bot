"""График мастера и исключения из него."""

from dataclasses import dataclass, field
from datetime import date, time

from barber_bot.domain.errors import InvalidWorkingHoursError
from barber_bot.domain.rules import BookingRules


@dataclass(frozen=True, slots=True)
class WorkingHours:
    start: time
    end: time

    def validate(self, rules: BookingRules) -> None:
        if self.start >= self.end:
            raise InvalidWorkingHoursError("Начало рабочего дня должно быть раньше конца")
        step = rules.grid_step_minutes
        for t in (self.start, self.end):
            if t.second or t.microsecond or t.minute % step:
                raise InvalidWorkingHoursError(f"Часы должны быть кратны {step} минутам")


@dataclass(frozen=True, slots=True)
class WeeklySchedule:
    """График: рабочие часы по дням недели (0 — понедельник). Отсутствие дня — выходной."""

    days: dict[int, WorkingHours] = field(default_factory=dict)

    def hours_on(self, weekday: int) -> WorkingHours | None:
        return self.days.get(weekday)

    def validate(self, rules: BookingRules) -> None:
        for weekday, hours in self.days.items():
            if not 0 <= weekday <= 6:
                raise InvalidWorkingHoursError(f"Нет такого дня недели: {weekday}")
            hours.validate(rules)


@dataclass(frozen=True, slots=True)
class ScheduleException:
    """Исключение: закрытый период (hours is None) или изменённые часы на каждую дату периода."""

    date_from: date
    date_to: date
    hours: WorkingHours | None = None
    id: int | None = None

    @property
    def is_closed(self) -> bool:
        return self.hours is None

    def covers(self, day: date) -> bool:
        return self.date_from <= day <= self.date_to

    def validate(self, rules: BookingRules) -> None:
        if self.date_from > self.date_to:
            raise InvalidWorkingHoursError("Дата начала исключения позже даты окончания")
        if self.hours is not None:
            self.hours.validate(rules)


def working_hours_on(
    day: date, schedule: WeeklySchedule, exceptions: list[ScheduleException]
) -> WorkingHours | None:
    """Рабочие часы на дату с учётом исключений. Если исключений несколько, побеждает последнее."""
    hours = schedule.hours_on(day.weekday())
    for exc in exceptions:
        if exc.covers(day):
            hours = exc.hours
    return hours
