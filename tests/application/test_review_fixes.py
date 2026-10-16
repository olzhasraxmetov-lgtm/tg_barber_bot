"""Регрессионные тесты на находки самопроверки (призрачные записи, склейка, порядок проверок)."""

from datetime import time, timedelta

import pytest
from support import CLIENT_TG, MONDAY, OTHER_TG, App, at, sid

from barber_bot.application.notifications import CancelledByMaster
from barber_bot.domain.errors import (
    InvalidNameError,
    TooLateToChangeError,
    WindowUnavailableError,
)
from barber_bot.domain.schedule import ScheduleException, WorkingHours

SUNDAY = MONDAY - timedelta(days=1)


async def test_deleting_opening_exception_over_appointments_needs_confirmation(
    registered: App,
) -> None:
    app = registered
    opened = await app.master.add_exception(
        ScheduleException(SUNDAY, SUNDAY, WorkingHours(time(12), time(15)))
    )
    assert opened.exception is not None and opened.exception.id is not None
    await app.client.book(CLIENT_TG, sid(app.haircut), at(SUNDAY, 12))

    result = await app.master.delete_exception(opened.exception.id)
    assert not result.applied
    assert len(result.conflicts) == 1
    assert len(await app.master.list_exceptions()) == 1  # ничего не удалено

    result = await app.master.delete_exception(opened.exception.id, cancel_conflicts=True)
    assert result.applied
    assert await app.master.list_exceptions() == []
    assert await app.client.my_appointments(CLIENT_TG) == []
    assert len(app.notifier.of(CancelledByMaster)) == 1


async def test_deleting_closing_exception_has_no_conflicts(registered: App) -> None:
    app = registered
    closed = await app.master.add_exception(ScheduleException(MONDAY, MONDAY))
    assert closed.exception is not None and closed.exception.id is not None
    result = await app.master.delete_exception(closed.exception.id)
    assert result.applied and result.conflicts == []


async def test_manual_phone_without_country_code_merges_with_bot_contact(app: App) -> None:
    await app.master.manual_booking("Иван", "701 555 55 55", sid(app.haircut), at(MONDAY, 11))
    await app.client.register(CLIENT_TG, "Иван", "+7 701 555 55 55")
    assert len(await app.client.my_appointments(CLIENT_TG)) == 1


async def test_late_reschedule_into_taken_window_says_too_late(registered: App) -> None:
    app = registered
    await app.client.register(OTHER_TG, "Борис", "+7 701 222 22 22")
    mine = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    await app.client.book(OTHER_TG, sid(app.haircut), at(MONDAY, 17))
    app.clock.set(at(MONDAY, 13))
    with pytest.raises(TooLateToChangeError):
        await app.client.reschedule(CLIENT_TG, mine.appointment.id or 0, at(MONDAY, 17))


async def test_master_can_book_within_three_hours_but_client_cannot(registered: App) -> None:
    app = registered
    app.clock.set(at(MONDAY, 10, 5))
    soon = at(MONDAY, 11)
    assert soon not in await app.client.free_windows(sid(app.haircut), MONDAY)
    with pytest.raises(WindowUnavailableError):
        await app.client.book(CLIENT_TG, sid(app.haircut), soon)

    assert soon in await app.master.free_windows(sid(app.haircut), MONDAY)
    details = await app.master.manual_booking("Иван", "7015555555", sid(app.haircut), soon)
    assert details.appointment.starts_at == soon


async def test_master_cannot_book_in_the_past(app: App) -> None:
    app.clock.set(at(MONDAY, 12))
    with pytest.raises(WindowUnavailableError):
        await app.master.manual_booking("Иван", "7015555555", sid(app.haircut), at(MONDAY, 11))


async def test_empty_client_name_is_rejected(app: App) -> None:
    with pytest.raises(InvalidNameError):
        await app.client.register(CLIENT_TG, "   ", "+7 701 111 11 11")
