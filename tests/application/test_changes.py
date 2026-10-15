from datetime import timedelta

import pytest
from support import CLIENT_TG, MONDAY, OTHER_TG, App, at, sid

from barber_bot.application.notifications import CancelledByClient, Rescheduled, VisitConfirmed
from barber_bot.domain.entities import Appointment, AppointmentStatus
from barber_bot.domain.errors import (
    NotFoundError,
    TooLateToChangeError,
    WindowTakenError,
    WindowUnavailableError,
)


async def test_overlapping_insert_is_rejected_by_grid_cells(registered: App) -> None:
    """Защита схемой (ADR 0001): даже в обход проверки окна пересечение не сохранится."""
    app = registered
    details = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    async with app.ctx.uow() as uow:
        clash = Appointment.book(
            client_id=details.client.id or 0,
            service=app.combo,
            starts_at=at(MONDAY, 14),
            now=app.clock.now(),
            rules=app.ctx.rules,
        )
        with pytest.raises(WindowTakenError):
            await uow.appointments.add(clash)


async def test_client_cancels_and_window_is_free_again(registered: App) -> None:
    app = registered
    booked = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    cancelled = await app.client.cancel(CLIENT_TG, booked.appointment.id or 0)

    assert cancelled.appointment.status is AppointmentStatus.CANCELLED
    assert len(app.notifier.of(CancelledByClient)) == 1
    assert await app.client.my_appointments(CLIENT_TG) == []
    assert at(MONDAY, 15) in await app.client.free_windows(sid(app.haircut), MONDAY)


async def test_client_cannot_cancel_less_than_three_hours_before(registered: App) -> None:
    app = registered
    booked = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    app.clock.set(at(MONDAY, 12, 30))
    assert not await app.client.can_change(CLIENT_TG, booked.appointment.id or 0)
    with pytest.raises(TooLateToChangeError):
        await app.client.cancel(CLIENT_TG, booked.appointment.id or 0)


async def test_client_cannot_touch_someone_elses_appointment(registered: App) -> None:
    app = registered
    await app.client.register(OTHER_TG, "Борис", "+7 701 222 22 22")
    booked = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    with pytest.raises(NotFoundError):
        await app.client.cancel(OTHER_TG, booked.appointment.id or 0)


async def test_reschedule_moves_cells_and_reminder(registered: App) -> None:
    app = registered
    booked = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    appt_id = booked.appointment.id or 0

    # Своя запись не мешает переносу на соседнее, пересекающееся окно.
    assert at(MONDAY, 15, 30) in await app.client.reschedule_windows(CLIENT_TG, appt_id, MONDAY)
    moved = await app.client.reschedule(CLIENT_TG, appt_id, at(MONDAY, 15, 30))

    assert moved.appointment.starts_at == at(MONDAY, 15, 30)
    assert moved.appointment.remind_at == at(MONDAY, 15, 30) - timedelta(hours=24)
    [note] = app.notifier.of(Rescheduled)
    assert note.old_start == at(MONDAY, 15)
    free = await app.client.free_windows(sid(app.beard), MONDAY)
    assert at(MONDAY, 15) in free
    assert at(MONDAY, 16) not in free


async def test_reschedule_into_taken_window_fails(registered: App) -> None:
    app = registered
    await app.client.register(OTHER_TG, "Борис", "+7 701 222 22 22")
    mine = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    await app.client.book(OTHER_TG, sid(app.haircut), at(MONDAY, 17))
    with pytest.raises(WindowUnavailableError):
        await app.client.reschedule(CLIENT_TG, mine.appointment.id or 0, at(MONDAY, 16, 30))


async def test_reschedule_too_late_is_rejected(registered: App) -> None:
    app = registered
    booked = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    app.clock.set(at(MONDAY, 13))
    with pytest.raises(TooLateToChangeError):
        await app.client.reschedule(
            CLIENT_TG, booked.appointment.id or 0, at(MONDAY + timedelta(days=1), 15)
        )


async def test_visit_confirmation_notifies_master_once(registered: App) -> None:
    app = registered
    booked = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    await app.client.confirm_visit(CLIENT_TG, booked.appointment.id or 0)
    await app.client.confirm_visit(CLIENT_TG, booked.appointment.id or 0)
    assert len(app.notifier.of(VisitConfirmed)) == 1
    [mine] = await app.client.my_appointments(CLIENT_TG)
    assert mine.appointment.visit_confirmed
