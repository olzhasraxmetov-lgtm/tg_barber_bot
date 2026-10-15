from datetime import timedelta

from support import CLIENT_TG, MONDAY, NOW, OTHER_TG, App, at, sid

from barber_bot.application.notifications import DailySummary, Reminder


async def test_reminder_is_sent_once_24_hours_before(registered: App) -> None:
    app = registered
    await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))

    app.clock.set(at(MONDAY, 15) - timedelta(hours=24, minutes=1))
    assert await app.jobs.send_due_reminders() == 0

    app.clock.advance(timedelta(minutes=1))
    assert await app.jobs.send_due_reminders() == 1
    assert await app.jobs.send_due_reminders() == 0
    [note] = app.notifier.of(Reminder)
    assert note.telegram_id == CLIENT_TG


async def test_missed_reminder_is_sent_after_downtime(registered: App) -> None:
    app = registered
    await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    app.clock.set(at(MONDAY, 9))  # бот лежал всё воскресенье
    assert await app.jobs.send_due_reminders() == 1


async def test_no_reminder_for_cancelled_or_started_appointments(registered: App) -> None:
    app = registered
    await app.client.register(OTHER_TG, "Борис", "+7 701 222 22 22")
    cancelled = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    await app.client.cancel(CLIENT_TG, cancelled.appointment.id or 0)
    await app.client.book(OTHER_TG, sid(app.haircut), at(MONDAY, 11))

    app.clock.set(at(MONDAY, 11, 30))  # запись Бориса уже идёт
    assert await app.jobs.send_due_reminders() == 0


async def test_no_reminder_when_booked_less_than_a_day_before(registered: App) -> None:
    app = registered
    app.clock.set(at(MONDAY, 8))
    await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    assert await app.jobs.send_due_reminders() == 0


async def test_rescheduled_appointment_is_reminded_for_new_time(registered: App) -> None:
    app = registered
    booked = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    tuesday = MONDAY + timedelta(days=1)
    await app.client.reschedule(CLIENT_TG, booked.appointment.id or 0, at(tuesday, 15))

    app.clock.set(at(MONDAY, 15) - timedelta(hours=24))
    assert await app.jobs.send_due_reminders() == 0
    app.clock.set(at(tuesday, 15) - timedelta(hours=24))
    assert await app.jobs.send_due_reminders() == 1


async def test_daily_summary_at_nine_once_per_day(registered: App) -> None:
    app = registered
    await app.client.register(OTHER_TG, "Борис", "+7 701 222 22 22")
    await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    await app.client.book(OTHER_TG, sid(app.beard), at(MONDAY, 10))

    app.clock.set(at(MONDAY, 8, 59))
    assert not await app.jobs.send_daily_summary()
    app.clock.set(at(MONDAY, 9))
    assert await app.jobs.send_daily_summary()
    assert not await app.jobs.send_daily_summary()  # после перезапуска не дублируется

    [summary] = app.notifier.of(DailySummary)
    assert summary.day == MONDAY
    assert [d.appointment.starts_at.hour for d in summary.appointments] == [10, 15]


async def test_no_daily_summary_on_empty_day(registered: App) -> None:
    app = registered
    app.clock.set(NOW)
    assert not await app.jobs.send_daily_summary()
    assert app.notifier.of(DailySummary) == []
