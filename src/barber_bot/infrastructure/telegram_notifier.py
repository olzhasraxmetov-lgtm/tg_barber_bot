"""Отправка уведомлений через Telegram: событие → получатель, текст и кнопки → send_message."""

import asyncio
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup

from barber_bot.application.notifications import (
    BookingConfirmation,
    CancelledByClient,
    CancelledByMaster,
    DailySummary,
    NewAppointment,
    Notification,
    Reminder,
    Rescheduled,
    VisitConfirmed,
)
from barber_bot.domain.rules import BookingRules
from barber_bot.presentation import keyboards, texts

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    chat_id: int
    text: str
    markup: InlineKeyboardMarkup | None = None


@dataclass(frozen=True, slots=True)
class NotificationRenderer:
    """Чистая часть: во что превращается каждое событие. Отдельно от отправки — ради тестов."""

    master_telegram_id: int
    fmt: texts.Formatter
    rules: BookingRules

    def render(self, notification: Notification) -> OutgoingMessage:
        fmt = self.fmt
        master = self.master_telegram_id
        match notification:
            case NewAppointment(details):
                return OutgoingMessage(
                    master, texts.new_appointment(details, fmt), keyboards.open_for_master(details)
                )
            case CancelledByClient(details):
                return OutgoingMessage(master, texts.cancelled_by_client(details, fmt))
            case Rescheduled(details, old_start):
                return OutgoingMessage(
                    master,
                    texts.rescheduled(details, old_start, fmt),
                    keyboards.open_for_master(details),
                )
            case VisitConfirmed(details):
                return OutgoingMessage(master, texts.visit_confirmed(details, fmt))
            case DailySummary(day, appointments):
                return OutgoingMessage(master, texts.daily_summary(day, appointments, fmt))
            case BookingConfirmation(telegram_id, details):
                return OutgoingMessage(
                    telegram_id,
                    texts.booking_confirmation(details, fmt, self.rules.min_lead),
                    keyboards.client_actions(details, confirm_visit=False),
                )
            case Reminder(telegram_id, details):
                return OutgoingMessage(
                    telegram_id,
                    texts.reminder(details, fmt),
                    keyboards.client_actions(details, confirm_visit=True),
                )
            case CancelledByMaster(telegram_id, details):
                return OutgoingMessage(
                    telegram_id, texts.cancelled_by_master(details, fmt), keyboards.book_again()
                )


class TelegramNotifier:
    def __init__(self, bot: Bot, renderer: NotificationRenderer) -> None:
        self._bot = bot
        self._renderer = renderer

    async def send(self, notification: Notification) -> None:
        """Ошибки Telegram не пробрасываем: действие уже выполнено, уведомление — вторично."""
        message = self._renderer.render(notification)
        kind = type(notification).__name__
        try:
            await self._send(message)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await self._send(message)
            except TelegramAPIError:
                logger.exception("Не удалось отправить %s в чат %s", kind, message.chat_id)
        except TelegramForbiddenError:
            logger.warning("Чат %s недоступен (бот заблокирован?), %s", message.chat_id, kind)
        except TelegramAPIError:
            logger.exception("Не удалось отправить %s в чат %s", kind, message.chat_id)

    async def _send(self, message: OutgoingMessage) -> None:
        await self._bot.send_message(message.chat_id, message.text, reply_markup=message.markup)
