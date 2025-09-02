FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV DEBIAN_FRONTEND=noninteractive
ENV UV_LINK_MODE=copy
ENV UV_SYSTEM_PYTHON=1

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY uv.lock /app/uv.lock

RUN uv sync --no-cache

COPY . /app

ENV PYTHONPATH=/app

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--reload"]