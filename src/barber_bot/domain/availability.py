"""Подсчёт свободных окон — чистые функции без I/O.

Все datetime — aware, в часовом поясе мастера; `now` тоже должен быть в нём, чтобы
`now.date()` означало «сегодня у мастера».
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo

from barber_bot.domain.rules import BookingRules
from barber_bot.domain.schedule import ScheduleException, WeeklySchedule, working_hours_on


@dataclass(frozen=True, slots=True)
class Interval:
    start: datetime
    end: datetime

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end and other.start < self.end


def horizon_dates(now: datetime, rules: BookingRules) -> list[date]:
    today = now.date()
    return [today + timedelta(days=i) for i in range(rules.horizon_days)]


def is_within_horizon(day: date, now: datetime, rules: BookingRules) -> bool:
    return 0 <= (day - now.date()).days < rules.horizon_days


def free_windows(
    *,
    day: date,
    duration: timedelta,
    schedule: WeeklySchedule,
    exceptions: list[ScheduleException],
    busy: list[Interval],
    now: datetime,
    tz: tzinfo,
    rules: BookingRules,
    min_lead: timedelta | None = None,
) -> list[datetime]:
    """Времена начала, в которые услуга длительностью `duration` целиком помещается в день.

    `min_lead` переопределяет запас до начала (мастеру он не нужен — только «не в прошлом»).
    """
    if not is_within_horizon(day, now, rules):
        return []
    hours = working_hours_on(day, schedule, exceptions)
    if hours is None:
        return []

    day_start = datetime.combine(day, hours.start, tzinfo=tz)
    day_end = datetime.combine(day, hours.end, tzinfo=tz)
    lunch = Interval(
        datetime.combine(day, rules.lunch_start, tzinfo=tz),
        datetime.combine(day, rules.lunch_end, tzinfo=tz),
    )
    earliest = now + (rules.min_lead if min_lead is None else min_lead)

    windows: list[datetime] = []
    start = day_start
    while start + duration <= day_end:
        candidate = Interval(start, start + duration)
        if (
            start >= earliest
            and not candidate.overlaps(lunch)
            and not any(candidate.overlaps(b) for b in busy)
        ):
            windows.append(start)
        start += rules.grid_step
    return windows


def grid_cells(starts_at: datetime, duration: timedelta, rules: BookingRules) -> list[datetime]:
    """Шаги сетки, которые занимает запись — по ним хранилище ловит двойную запись."""
    count = int(duration / rules.grid_step)
    return [starts_at + rules.grid_step * i for i in range(count)]
