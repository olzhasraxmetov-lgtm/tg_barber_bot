import logging

from barber_bot.application.notifications import Notification

logger = logging.getLogger(__name__)


class LoggingNotifier:
    """Временная заглушка: пишет уведомления в лог, пока нет отправки через Telegram."""

    async def send(self, notification: Notification) -> None:
        logger.info("Уведомление: %r", notification)
