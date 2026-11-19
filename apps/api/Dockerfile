# Kompatibel dengan builder lama (docker.io di WSL tanpa buildx) maupun BuildKit.
# ---- build: install dependency dengan uv (lockfile wajib cocok) ----
FROM ghcr.io/astral-sh/uv:0.7-python3.12-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# ---- runtime ----
FROM python:3.12-slim-bookworm
RUN useradd --system --uid 10001 --home /app app
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --from=build --chown=app:app /app/alembic.ini /app/alembic.ini
COPY --from=build --chown=app:app /app/alembic /app/alembic
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BHV_API_DIR=/app
USER app
EXPOSE 8000
# RUN_MIGRATIONS=1 -> migrasi otomatis saat start (dipakai compose lokal/CI).
# Produksi: migrasi dijalankan sebagai one-shot container sebelum deploy.
CMD ["sh", "-c", "if [ \"$RUN_MIGRATIONS\" = \"1\" ]; then bhv migrate; fi && exec uvicorn bhv.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
