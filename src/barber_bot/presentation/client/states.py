from aiogram.fsm.state import State, StatesGroup


class Registration(StatesGroup):
    name = State()
    enter_name = State()
    phone = State()


class Profile(StatesGroup):
    view = State()
    edit_name = State()
    edit_phone = State()


class ClientMenu(StatesGroup):
    main = State()
    services = State()


class Booking(StatesGroup):
    """Запись и перенос: при переносе в start_data лежит `appointment_id`, начало — с даты."""

    service = State()
    date = State()
    time = State()
    confirm = State()


class MyAppointments(StatesGroup):
    list = State()
    card = State()
    cancel = State()
