class DomainError(Exception):
    """Нарушение бизнес-правила. Presentation превращает его в понятный текст."""


class WindowTakenError(DomainError):
    """Свободное окно заняли, пока клиент выбирал."""


class WindowUnavailableError(DomainError):
    """Время не является свободным окном: вне графика, на обеде, слишком скоро или вне горизонта."""


class TooLateToChangeError(DomainError):
    """До начала записи меньше минимального запаса — клиент не может её отменить или перенести."""


class ServiceHiddenError(DomainError):
    """Услуга скрыта мастером, записаться на неё нельзя."""


class InvalidDurationError(DomainError):
    """Длительность услуги не кратна шагу сетки."""


class InvalidPhoneError(DomainError):
    """Телефон не похож на номер."""


class InvalidWorkingHoursError(DomainError):
    """Рабочие часы пустые, перевёрнуты или не выровнены по шагу сетки."""


class AppointmentNotActiveError(DomainError):
    """Действие над уже отменённой записью."""


class AppointmentNotPastError(DomainError):
    """Неявку можно отметить только на записи, которая уже началась."""


class NotFoundError(DomainError):
    """Запрошенный объект не найден или не принадлежит клиенту."""
