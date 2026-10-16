from datetime import datetime, tzinfo


class SystemClock:
    """Настоящие часы: текущее время в часовом поясе мастера."""

    def __init__(self, tz: tzinfo) -> None:
        self._tz = tz

    def now(self) -> datetime:
        return datetime.now(self._tz)
