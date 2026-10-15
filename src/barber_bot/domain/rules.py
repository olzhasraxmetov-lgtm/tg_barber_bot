"""Параметры правил записи. В v1 это константы, мастер их в боте не меняет."""

from dataclasses import dataclass
from datetime import time, timedelta


@dataclass(frozen=True, slots=True)
class BookingRules:
    grid_step: timedelta = timedelta(minutes=30)
    # Записаться можно на сегодня и ещё horizon_days - 1 дней вперёд.
    horizon_days: int = 30
    # Минимальный запас до начала записи — для записи, отмены и переноса клиентом.
    min_lead: timedelta = timedelta(hours=3)
    lunch_start: time = time(13, 0)
    lunch_end: time = time(14, 0)
    reminder_before: timedelta = timedelta(hours=24)
    summary_time: time = time(9, 0)

    @property
    def grid_step_minutes(self) -> int:
        return int(self.grid_step.total_seconds() // 60)


DEFAULT_RULES = BookingRules()
