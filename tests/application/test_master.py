from datetime import time, timedelta

import pytest
from support import CLIENT_TG, MONDAY, OTHER_TG, App, at, sid

from barber_bot.application.notifications import BookingConfirmation, CancelledByMaster, Reminder
from barber_bot.domain.entities import AppointmentStatus, CancelledBy
from barber_bot.domain.errors import AppointmentNotPastError, InvalidDurationError
from barber_bot.domain.schedule import ScheduleException, WeeklySchedule, WorkingHours

TUESDAY = MONDAY + timedelta(days=1)


async def test_master_sees_day_schedule_in_time_order(registered: App) -> None:
    app = registered
    await app.client.register(OTHER_TG, "Борис", "+7 701 222 22 22")
    await app.client.book(OTHER_TG, sid(app.haircut), at(MONDAY, 17))
    await app.client.book(CLIENT_TG, sid(app.beard), at(MONDAY, 10))
    schedule = await app.master.schedule_for(MONDAY)
    assert [(d.client.name, d.appointment.starts_at.hour) for d in schedule] == [
        ("Алексей", 10),
        ("Борис", 17),
    ]


async def test_master_cancel_notifies_client_with_reason(registered: App) -> None:
    app = registered
    booked = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    app.clock.set(at(MONDAY, 14))  # мастер может отменить и в последний момент
    details = await app.master.cancel(booked.appointment.id or 0, "Заболел")
    assert details.appointment.cancelled_by is CancelledBy.MASTER
    [note] = app.notifier.of(CancelledByMaster)
    assert note.telegram_id == CLIENT_TG
    assert note.details.appointment.cancel_reason == "Заболел"


async def test_manual_booking_without_telegram_sends_nothing(app: App) -> None:
    details = await app.master.manual_booking(
        "Иван", "8 701 555 55 55", sid(app.haircut), at(MONDAY, 11)
    )
    assert details.appointment.is_manual
    assert details.client.telegram_id is None
    assert app.notifier.sent == []
    assert await app.client.free_windows(sid(app.beard), MONDAY) != []
    assert at(MONDAY, 11) not in await app.client.free_windows(sid(app.beard), MONDAY)


async def test_manual_client_joins_bot_and_gets_appointment_and_reminder(app: App) -> None:
    await app.master.manual_booking("Иван", "8 701 555 55 55", sid(app.haircut), at(MONDAY, 11))
    await app.client.register(CLIENT_TG, "Иван Петров", "+7 (701) 555-55-55")

    [mine] = await app.client.my_appointments(CLIENT_TG)
    assert mine.appointment.is_manual
    assert mine.client.name == "Иван Петров"

    app.clock.set(at(MONDAY, 11) - timedelta(hours=24))
    assert await app.jobs.send_due_reminders() == 1
    assert app.notifier.of(Reminder)[0].telegram_id == CLIENT_TG


async def test_manual_booking_for_known_bot_client_sends_confirmation(registered: App) -> None:
    app = registered
    await app.master.manual_booking("Алексей", "87011111111", sid(app.haircut), at(MONDAY, 11))
    [note] = app.notifier.of(BookingConfirmation)
    assert note.telegram_id == CLIENT_TG
    assert len(await app.client.my_appointments(CLIENT_TG)) == 1


async def test_changing_phone_to_manual_clients_phone_merges_profiles(registered: App) -> None:
    app = registered
    await app.master.manual_booking("Алексей", "87019999999", sid(app.haircut), at(MONDAY, 11))
    await app.client.book(CLIENT_TG, sid(app.beard), at(MONDAY, 15))
    await app.client.register(CLIENT_TG, "Алексей", "87019999999")
    assert len(await app.client.my_appointments(CLIENT_TG)) == 2


async def test_exception_over_appointments_needs_confirmation(registered: App) -> None:
    app = registered
    booked = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    sick = ScheduleException(MONDAY, TUESDAY)

    result = await app.master.add_exception(sick)
    assert not result.applied
    assert [d.appointment.id for d in result.conflicts] == [booked.appointment.id]
    assert await app.master.list_exceptions() == []
    assert len(await app.client.my_appointments(CLIENT_TG)) == 1

    result = await app.master.add_exception(sick, cancel_conflicts=True)
    assert result.applied
    assert result.exception is not None
    assert await app.client.my_appointments(CLIENT_TG) == []
    [note] = app.notifier.of(CancelledByMaster)
    assert note.details.appointment.status is AppointmentStatus.CANCELLED
    assert await app.client.free_windows(sid(app.haircut), MONDAY) == []


async def test_exception_with_shorter_hours_cancels_only_what_does_not_fit(registered: App) -> None:
    app = registered
    await app.client.register(OTHER_TG, "Борис", "+7 701 222 22 22")
    await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 11))
    late = await app.client.book(OTHER_TG, sid(app.haircut), at(MONDAY, 17))
    short_day = ScheduleException(MONDAY, MONDAY, WorkingHours(time(10), time(16)))
    result = await app.master.add_exception(short_day)
    assert [d.appointment.id for d in result.conflicts] == [late.appointment.id]


async def test_exception_can_be_deleted_to_reopen_day(registered: App) -> None:
    app = registered
    result = await app.master.add_exception(ScheduleException(MONDAY, MONDAY))
    assert result.exception is not None and result.exception.id is not None
    await app.master.delete_exception(result.exception.id)
    assert await app.client.free_windows(sid(app.haircut), MONDAY) != []


async def test_weekly_schedule_change_over_appointments_needs_confirmation(registered: App) -> None:
    app = registered
    await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    without_monday = WeeklySchedule({d: WorkingHours(time(10), time(20)) for d in range(1, 5)})

    result = await app.master.set_weekly_schedule(without_monday)
    assert not result.applied and len(result.conflicts) == 1
    assert (await app.master.get_weekly_schedule()).hours_on(0) is not None

    result = await app.master.set_weekly_schedule(without_monday, cancel_conflicts=True)
    assert result.applied
    assert (await app.master.get_weekly_schedule()).hours_on(0) is None
    assert len(app.notifier.of(CancelledByMaster)) == 1


async def test_no_show_is_marked_after_start_and_reverted(registered: App) -> None:
    app = registered
    booked = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    appt_id = booked.appointment.id or 0
    with pytest.raises(AppointmentNotPastError):
        await app.master.set_no_show(appt_id, True)
    app.clock.set(at(MONDAY, 16))
    assert (await app.master.set_no_show(appt_id, True)).appointment.no_show
    assert not (await app.master.set_no_show(appt_id, False)).appointment.no_show


async def test_service_crud_and_validation(app: App) -> None:
    svc = await app.master.add_service("Камуфляж седины", 30, 4000)
    with pytest.raises(InvalidDurationError):
        await app.master.add_service("Странная", 45, 1000)
    await app.master.update_service(sid(svc), is_hidden=True)
    assert "Камуфляж седины" not in [s.name for s in await app.client.list_services()]
    assert "Камуфляж седины" in [s.name for s in await app.master.list_services()]
    await app.master.update_service(sid(svc), is_hidden=False)
    assert "Камуфляж седины" in [s.name for s in await app.client.list_services()]
