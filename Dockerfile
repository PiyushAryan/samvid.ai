# syntax=docker/dockerfile:1.7

FROM node:22.21.1-bookworm-slim AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12.10-slim-bookworm AS python-builder
RUN python -m pip install --no-cache-dir uv==0.11.17
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra api --extra rabbitmq --no-install-project
COPY src/ ./src/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra api --extra rabbitmq --no-editable

FROM python:3.12.10-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000
WORKDIR /app

RUN groupadd --system --gid 10001 samvid \
    && useradd --system --uid 10001 --gid samvid --home-dir /app --shell /usr/sbin/nologin samvid \
    && mkdir -p /app/data/contracts /app/data/inbound-email \
    && chown -R samvid:samvid /app

COPY --from=python-builder --chown=samvid:samvid /app/.venv /app/.venv
COPY --from=frontend-builder --chown=samvid:samvid /build/frontend/dist /app/frontend/dist

USER samvid
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '8000') + '/health', timeout=3)"

CMD ["sh", "-c", "exec uvicorn contractmate.app:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
