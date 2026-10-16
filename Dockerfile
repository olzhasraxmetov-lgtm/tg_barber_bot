FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Сначала только зависимости — этот слой пересобирается лишь при изменении uv.lock.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project

# Проект ставится editable: миграции ищутся по пути исходников (alembic.ini, migrations/ в /app).
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Директория базы создаётся заранее с владельцем app — новый volume унаследует права.
RUN useradd --create-home --uid 1000 app && mkdir -p data && chown app:app data
USER app

# Миграции применяются при старте бота; демо-данные — если база пустая (SEED_DEMO).
CMD ["bot"]
