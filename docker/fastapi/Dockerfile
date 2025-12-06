FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV DEBIAN_FRONTEND=noninteractive
ENV UV_LINK_MODE=copy
ENV UV_SYSTEM_PYTHON=1

WORKDIR /app

COPY apps/server/pyproject.toml /app/pyproject.toml
COPY apps/server/uv.lock /app/uv.lock

RUN uv sync --no-cache

# COPY . /app
# COPY api/ /app/api
# COPY core/ /app/core
# COPY models/ /app/models
# COPY models/ /app/models
# COPY schemas/ /app/schemas
# COPY services/ /app/services
# COPY main.py /app/main.py
# COPY migrations/ /app/migrations
# COPY alembic.ini /app/alembic.ini

COPY apps/server/ /app/

ENV PYTHONPATH=/app

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--reload"]