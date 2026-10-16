"""Короткое сообщение над окном диалога («Запись отменена»), показывается один раз.

Приходит в диалог тремя путями: `start(data={"flash": ...})`, `done(result={"flash": ...})`
от дочернего диалога или `set_flash` из своего же обработчика.
"""

from typing import Any

from aiogram_dialog import Data, DialogManager

KEY = "flash"


def set_flash(manager: DialogManager, text: str) -> None:
    manager.dialog_data[KEY] = text


def pop_flash(manager: DialogManager) -> str:
    text: str = manager.dialog_data.pop(KEY, "")
    return text + "\n\n" if text else ""


def flash_result(text: str) -> dict[str, str]:
    return {KEY: text}


async def on_start(start_data: Data, manager: DialogManager) -> None:
    """Переносит start_data в dialog_data — и флеш, и прочие параметры запуска."""
    if isinstance(start_data, dict):
        manager.dialog_data.update(start_data)


async def on_result(_: Data, result: Any, manager: DialogManager) -> None:
    if isinstance(result, dict) and KEY in result:
        set_flash(manager, result[KEY])
