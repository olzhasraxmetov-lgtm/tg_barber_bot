from aiogram.fsm.state import State, StatesGroup


class MasterMenu(StatesGroup):
    main = State()


class DaySchedule(StatesGroup):
    """Расписание дня и карточка записи. В start_data — `day` и/или `appointment_id`."""

    pick_date = State()
    day = State()
    card = State()
    cancel = State()


class ManualBooking(StatesGroup):
    name = State()
    phone = State()
    service = State()
    date = State()
    time = State()
    confirm = State()


class WeeklyHours(StatesGroup):
    week = State()
    day = State()
    pick_start = State()
    pick_end = State()
    conflicts = State()


class Exceptions(StatesGroup):
    list = State()
    card = State()
    pick_from = State()
    pick_to = State()
    kind = State()
    pick_start = State()
    pick_end = State()
    conflicts = State()


class Services(StatesGroup):
    list = State()
    card = State()
    name = State()
    price = State()
    duration = State()
