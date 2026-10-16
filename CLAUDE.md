## Agent skills

- Глоссарий домена — `CONTEXT.md` в корне. Называй доменные понятия его терминами, а не синонимами из `_Avoid_`.
- ADR лежат в `docs/adr/` — прочитай относящиеся к области, прежде чем её менять.

## Проект

Telegram-бот онлайн-записи к одному мастеру-барберу; портфолио-проект. Чистая архитектура
(ADR 0002): `src/barber_bot/{domain,application,infrastructure,presentation}`, зависимости только внутрь.

- Требования: `.tracker/barber-bot-v1/spec.md`; план и статус шагов: `.tracker/barber-bot-v1/plan.md`
  (`.tracker/` не в git — рабочие документы). Начиная шаг, прочитай план и спеку.
- Команды (uv установлен через pip, поэтому `python -m uv`):
  - `python -m uv run pytest -q`
  - `python -m uv run ruff format . && python -m uv run ruff check .`
  - `python -m uv run mypy` (проверяет `src` и `tests`, strict)
- Схема БД меняется только миграциями Alembic (`migrations/`); после изменения моделей —
  `alembic revision --autogenerate`, затем `alembic check`.
- Тесты двух уровней: чистый домен (`tests/domain`) и use cases на настоящем SQLite, поднятом
  миграциями, с подставными часами и уведомлениями (`tests/application`).
- Коммиты на русском в стиле conventional commits; после каждого законченного шага с зелёными
  проверками — коммит и push в `origin/main`.
