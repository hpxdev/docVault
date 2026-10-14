# syntax=docker/dockerfile:1
FROM python:3.12-slim-trixie AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    TIKTOKEN_CACHE_DIR=/opt/tiktoken \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Bake the tokenizer files into the image so containers never download them at runtime.
RUN python -c "import tiktoken; tiktoken.get_encoding('o200k_base'); tiktoken.get_encoding('cl100k_base')"

# Runtime image (api + worker)
FROM base AS runtime
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN useradd --create-home --uid 1000 vault && mkdir -p /data/storage && chown -R vault /data
USER vault
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]

# Test image: dev dependencies; source is bind-mounted by compose.test.yml
FROM base AS test
RUN uv sync --frozen --no-install-project
COPY . .
CMD ["pytest", "-q"]
