import asyncio
from datetime import timedelta

import pytest
from support import CLIENT_TG, MONDAY, NOW, OTHER_TG, App, at, sid

from barber_bot.application.notifications import BookingConfirmation, NewAppointment
from barber_bot.domain.errors import (
    ClientNotRegisteredError,
    PhoneTakenError,
    ServiceHiddenError,
    WindowTakenError,
    WindowUnavailableError,
)


async def test_booking_notifies_master_and_client(registered: App) -> None:
    app = registered
    details = await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))

    assert details.appointment.starts_at == at(MONDAY, 15)
    assert details.service_name == "Стрижка"
    [master_note] = app.notifier.of(NewAppointment)
    assert master_note.details.client.phone == "77011111111"
    [client_note] = app.notifier.of(BookingConfirmation)
    assert client_note.telegram_id == CLIENT_TG


async def test_booked_window_disappears_from_free_windows(registered: App) -> None:
    app = registered
    await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    windows = await app.client.free_windows(sid(app.combo), MONDAY)
    starts = {w.strftime("%H:%M") for w in windows}
    assert {"13:30", "14:00", "14:30", "15:00", "15:30"}.isdisjoint(starts)
    assert "16:00" in starts


async def test_second_client_gets_window_unavailable_for_same_time(registered: App) -> None:
    app = registered
    await app.client.register(OTHER_TG, "Борис", "+7 701 222 22 22")
    await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    with pytest.raises(WindowUnavailableError):
        await app.client.book(OTHER_TG, sid(app.beard), at(MONDAY, 15, 30))


async def test_concurrent_bookings_of_same_window_one_wins(registered: App) -> None:
    """Оба проверили окно до записи друг друга — спасает UNIQUE на шагах сетки."""
    app = registered
    await app.client.register(OTHER_TG, "Борис", "+7 701 222 22 22")
    results = await asyncio.gather(
        app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15)),
        app.client.book(OTHER_TG, sid(app.combo), at(MONDAY, 14, 30)),
        return_exceptions=True,
    )
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) == 1
    assert isinstance(errors[0], WindowTakenError | WindowUnavailableError)
    assert len(app.notifier.of(NewAppointment)) == 1


async def test_cannot_book_outside_free_windows(registered: App) -> None:
    app = registered
    for bad in (at(MONDAY, 13), at(MONDAY, 9), at(MONDAY, 19, 30), at(MONDAY, 15, 15)):
        with pytest.raises(WindowUnavailableError):
            await app.client.book(CLIENT_TG, sid(app.haircut), bad)
    with pytest.raises(WindowUnavailableError):
        await app.client.book(CLIENT_TG, sid(app.haircut), NOW + timedelta(days=40))


async def test_cannot_book_hidden_service(registered: App) -> None:
    app = registered
    await app.master.update_service(sid(app.beard), is_hidden=True)
    assert [s.name for s in await app.client.list_services()] == ["Стрижка", "Стрижка + борода"]
    with pytest.raises(ServiceHiddenError):
        await app.client.book(CLIENT_TG, sid(app.beard), at(MONDAY, 15))


async def test_unregistered_client_cannot_book(app: App) -> None:
    with pytest.raises(ClientNotRegisteredError):
        await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))


async def test_available_dates_skip_days_off(registered: App) -> None:
    dates = await registered.client.available_dates(sid(registered.haircut))
    assert len(dates) > 0
    assert all(d.weekday() < 5 for d in dates)
    assert dates[0] == NOW.date()


async def test_service_change_does_not_touch_existing_appointments(registered: App) -> None:
    app = registered
    await app.client.book(CLIENT_TG, sid(app.haircut), at(MONDAY, 15))
    await app.master.update_service(sid(app.haircut), duration_minutes=90, price=6000)
    [mine] = await app.client.my_appointments(CLIENT_TG)
    assert (mine.appointment.duration_minutes, mine.appointment.price) == (60, 5000)


async def test_registration_is_asked_once_and_profile_can_change(app: App) -> None:
    first = await app.client.register(CLIENT_TG, "Лёша", "87011111111")
    second = await app.client.register(CLIENT_TG, "Алексей", "+7 701 333 33 33")
    assert first.id == second.id
    profile = await app.client.get_profile(CLIENT_TG)
    assert profile is not None
    assert (profile.name, profile.phone) == ("Алексей", "77013333333")


async def test_phone_of_another_telegram_account_is_rejected(registered: App) -> None:
    with pytest.raises(PhoneTakenError):
        await registered.client.register(OTHER_TG, "Борис", "+7 701 111 11 11")
