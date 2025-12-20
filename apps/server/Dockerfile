# FROM python:3.13-slim
# COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
# ENV DEBIAN_FRONTEND=noninteractive
# ENV UV_LINK_MODE=copy
# # ENV UV_SYSTEM_PYTHON=1

# WORKDIR /app

# COPY pyproject.toml uv.lock ./

# RUN uv venv && \
#     uv sync --frozen --no-dev

# COPY server/. ./

# ENV PATH="/app/.venv/bin:$PATH"
# ENV PYTHONPATH=/app

# EXPOSE 8000

# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# # CMD ["/bin/bash", "scripts/run.sh"]
# # CMD ["uv", "run", "--no-sync", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--reload"]

FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV DEBIAN_FRONTEND=noninteractive \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copier dans un sous-dossier server/
COPY ./apps/server .

EXPOSE 8000

# Import depuis server.main
CMD ["uv", "run", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
