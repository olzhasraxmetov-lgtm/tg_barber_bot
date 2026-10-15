"""Общие константы, подставные порты и хелперы для тестов use cases."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import TypeVar
from zoneinfo import ZoneInfo

from barber_bot.application.client_actions import ClientActions
from barber_bot.application.context import AppContext
from barber_bot.application.jobs import BackgroundJobs
from barber_bot.application.master_actions import MasterActions
from barber_bot.application.notifications import Notification
from barber_bot.domain.entities import Service

TZ = ZoneInfo("Asia/Almaty")
# Четверг, 15 октября 2026, 09:00 у мастера. Ближайший понедельник — 19 октября.
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=TZ)
MONDAY = date(2026, 10, 19)
CLIENT_TG = 111
OTHER_TG = 222

N = TypeVar("N")


def at(day: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(day, time(h, m), tzinfo=TZ)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


@dataclass
class RecordingNotifier:
    sent: list[Notification] = field(default_factory=list)

    async def send(self, notification: Notification) -> None:
        self.sent.append(notification)

    def of(self, kind: type[N]) -> list[N]:
        return [n for n in self.sent if isinstance(n, kind)]

    def clear(self) -> None:
        self.sent.clear()


@dataclass
class App:
    ctx: AppContext
    clock: FakeClock
    notifier: RecordingNotifier
    client: ClientActions
    master: MasterActions
    jobs: BackgroundJobs
    haircut: Service  # 60 мин
    beard: Service  # 30 мин
    combo: Service  # 90 мин


def sid(service: Service) -> int:
    assert service.id is not None
    return service.id
