"""Настройки из переменных окружения и файла .env."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: SecretStr
    master_telegram_id: int
    timezone: str = "Asia/Almaty"
    database_url: str = "sqlite+aiosqlite:///data/barber.db"
    currency: str = "₸"
    phone_country_code: str = "7"
    # Демо-услуги и график при первом запуске — чтобы в боте сразу можно было записаться.
    seed_demo: bool = True

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"Неизвестный часовой пояс: {value}") from e
        return value

    @field_validator("phone_country_code")
    @classmethod
    def _digits_only(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("Код страны — только цифры, без «+»")
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
