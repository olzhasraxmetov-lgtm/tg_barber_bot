"""Общие обработчики ошибок: доменные правила → понятный текст, устаревшие кнопки → меню."""

import logging

from aiogram import Router
from aiogram.filters import ExceptionTypeFilter
from aiogram.types import ErrorEvent
from aiogram_dialog import DialogManager
from aiogram_dialog.api.exceptions import OutdatedIntent, UnknownIntent, UnknownState

from barber_bot.domain.errors import DomainError
from barber_bot.presentation import texts
from barber_bot.presentation.home import open_home

logger = logging.getLogger(__name__)

router = Router(name="errors")


@router.error(ExceptionTypeFilter(DomainError))
async def on_domain_error(event: ErrorEvent) -> None:
    assert isinstance(event.exception, DomainError)
    text = texts.error_text(event.exception)
    update = event.update
    if update.callback_query is not None:
        await update.callback_query.answer(text, show_alert=True)
    elif update.message is not None:
        await update.message.answer(text)


@router.error(ExceptionTypeFilter(UnknownIntent, OutdatedIntent, UnknownState))
async def on_stale_dialog(event: ErrorEvent, dialog_manager: DialogManager) -> None:
    """Кнопка из старого сообщения (или бот перезапустился и забыл диалоги)."""
    logger.info("Устаревший диалог: %s", event.exception)
    update = event.update
    user = None
    if update.callback_query is not None:
        await update.callback_query.answer(texts.STALE_MENU)
        user = update.callback_query.from_user
    elif update.message is not None:
        user = update.message.from_user
    if user is not None:
        await open_home(dialog_manager, user.id)
