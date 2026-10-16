"""Зависимости из `dp.workflow_data` для колбэков диалогов.

Getters получают их сразу keyword-аргументами."""

from typing import cast

from aiogram.types import User
from aiogram_dialog import DialogManager

from barber_bot.application.client_actions import ClientActions
from barber_bot.application.ports import Clock
from barber_bot.domain.rules import BookingRules
from barber_bot.presentation.texts import Formatter


def client_actions(manager: DialogManager) -> ClientActions:
    return cast(ClientActions, manager.middleware_data["client_actions"])


def clock(manager: DialogManager) -> Clock:
    return cast(Clock, manager.middleware_data["clock"])


def formatter(manager: DialogManager) -> Formatter:
    return cast(Formatter, manager.middleware_data["fmt"])


def rules(manager: DialogManager) -> BookingRules:
    return cast(BookingRules, manager.middleware_data["rules"])


def user(manager: DialogManager) -> User | None:
    """Автор события — aiogram кладёт его в данные любого апдейта, включая ошибки."""
    return cast(User | None, manager.middleware_data.get("event_from_user"))


def user_id(manager: DialogManager) -> int:
    user_ = user(manager)
    if user_ is None:
        raise RuntimeError("Событие без пользователя")
    return user_.id
