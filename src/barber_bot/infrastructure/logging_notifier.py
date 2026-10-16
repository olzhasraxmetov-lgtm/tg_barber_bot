import logging

from barber_bot.application.notifications import Notification

logger = logging.getLogger(__name__)


class LoggingNotifier:
    """Пишет уведомления в лог — для запусков без бота (seed-скрипт)."""

    async def send(self, notification: Notification) -> None:
        logger.info("Уведомление: %r", notification)
