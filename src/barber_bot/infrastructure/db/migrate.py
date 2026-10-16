"""Применение миграций Alembic из кода: при старте бота и в тестах."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[4]


def ensure_database_dir(url: str) -> None:
    """SQLite создаёт файл базы сам, а директорию под него — нет."""
    database = make_url(url).database
    if database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)


def upgrade_to_head(url: str) -> None:
    ensure_database_dir(url)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    # Логирование настраивает приложение; fileConfig из alembic.ini отключил бы его логгеры.
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
