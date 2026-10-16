"""Кто мастер и в каком режиме он сейчас пользуется ботом."""


class Roles:
    """Мастер — владелец `MASTER_TELEGRAM_ID`. Режим клиента хранится в памяти процесса:
    после перезапуска бот снова открывает мастеру его меню."""

    def __init__(self, master_telegram_id: int) -> None:
        self._master_id = master_telegram_id
        self._client_mode = False

    def is_master(self, telegram_id: int) -> bool:
        return telegram_id == self._master_id

    def acts_as_master(self, telegram_id: int) -> bool:
        return self.is_master(telegram_id) and not self._client_mode

    def set_client_mode(self, enabled: bool) -> None:
        self._client_mode = enabled
