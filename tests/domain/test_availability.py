from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from barber_bot.domain.availability import Interval, free_windows, grid_cells, horizon_dates
from barber_bot.domain.rules import DEFAULT_RULES
from barber_bot.domain.schedule import ScheduleException, WeeklySchedule, WorkingHours

TZ = ZoneInfo("Asia/Almaty")
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=TZ)  # четверг
MONDAY = date(2026, 10, 19)
SUNDAY = date(2026, 10, 18)
HOUR = timedelta(hours=1)

SCHEDULE = WeeklySchedule({d: WorkingHours(time(10), time(20)) for d in range(5)})


def at(day: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(day, time(h, m), tzinfo=TZ)


def windows(
    day: date = MONDAY,
    duration: timedelta = HOUR,
    *,
    exceptions: list[ScheduleException] | None = None,
    busy: list[Interval] | None = None,
    now: datetime = NOW,
) -> list[datetime]:
    return free_windows(
        day=day,
        duration=duration,
        schedule=SCHEDULE,
        exceptions=exceptions or [],
        busy=busy or [],
        now=now,
        tz=TZ,
        rules=DEFAULT_RULES,
    )


def times(result: list[datetime]) -> list[str]:
    return [w.strftime("%H:%M") for w in result]


def test_regular_day_has_30_minute_grid_without_lunch() -> None:
    assert times(windows()) == [
        "10:00", "10:30", "11:00", "11:30", "12:00",
        "14:00", "14:30", "15:00", "15:30", "16:00", "16:30",
        "17:00", "17:30", "18:00", "18:30", "19:00",
    ]  # fmt: skip


def test_service_must_fit_before_end_of_day() -> None:
    assert times(windows(duration=timedelta(minutes=90)))[-1] == "18:30"


def test_long_service_cannot_cross_lunch() -> None:
    result = times(windows(duration=timedelta(minutes=90)))
    assert "11:30" in result
    assert "12:00" not in result
    assert "12:30" not in result
    assert "14:00" in result


def test_day_off_by_schedule_has_no_windows() -> None:
    assert windows(SUNDAY) == []


def test_closed_exception_removes_day() -> None:
    sick = ScheduleException(MONDAY, MONDAY + timedelta(days=2))
    assert windows(exceptions=[sick]) == []


def test_exception_with_changed_hours_overrides_schedule() -> None:
    short = ScheduleException(MONDAY, MONDAY, WorkingHours(time(10), time(16)))
    assert times(windows(exceptions=[short]))[-1] == "15:00"


def test_exception_can_open_a_day_off() -> None:
    extra = ScheduleException(SUNDAY, SUNDAY, WorkingHours(time(12), time(15)))
    assert times(windows(SUNDAY, exceptions=[extra])) == ["12:00", "14:00"]


def test_busy_intervals_block_overlapping_windows() -> None:
    busy = [Interval(at(MONDAY, 15), at(MONDAY, 16, 30))]
    result = times(windows(busy=busy))
    assert "14:00" in result
    assert "14:30" not in result  # 14:30–15:30 пересекает занятое
    assert "16:00" not in result
    assert "16:30" in result


def test_windows_start_at_least_three_hours_from_now() -> None:
    now = at(MONDAY, 10, 15)
    assert times(windows(now=now))[0] == "14:00"  # 13:15 и раньше нельзя, а 13:30 — обед


@pytest.mark.parametrize(
    ("offset_days", "expected_open"),
    [(0, True), (29, True), (30, False)],  # пн, вт, ср — все рабочие по графику
)
def test_horizon_is_30_days_including_today(offset_days: int, expected_open: bool) -> None:
    day = MONDAY + timedelta(days=offset_days)
    assert bool(windows(day, now=at(MONDAY, 6))) is expected_open


def test_past_day_has_no_windows() -> None:
    assert windows(MONDAY, now=at(MONDAY + timedelta(days=1), 6)) == []


def test_horizon_dates_count() -> None:
    dates = horizon_dates(NOW, DEFAULT_RULES)
    assert len(dates) == 30
    assert dates[0] == NOW.date()


def test_grid_cells_cover_whole_duration() -> None:
    cells = grid_cells(at(MONDAY, 10), timedelta(minutes=90), DEFAULT_RULES)
    assert [c.strftime("%H:%M") for c in cells] == ["10:00", "10:30", "11:00"]
