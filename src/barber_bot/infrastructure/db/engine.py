"""Подключение к SQLite.

Драйвер sqlite3 по умолчанию сам решает, когда начинать транзакцию, и не шлёт BEGIN перед
SELECT — изоляция неполная. По рецепту из документации SQLAlchemy для aiosqlite отключаем это
поведение и начинаем транзакцию сами. BEGIN IMMEDIATE сразу берёт блокировку записи: для бота
с одним процессом это убирает SQLITE_BUSY при повышении блокировки ценой сериализации транзакций.
"""

from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(url: str) -> AsyncEngine:
    engine = create_async_engine(url)

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    @event.listens_for(engine.sync_engine, "begin")
    def _on_begin(conn: Any) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
