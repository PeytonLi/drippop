# Build context: repo root.  docker build -f backend/Dockerfile -t drippop-backend .
FROM python:3.12.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /uvx /bin/

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/api ./api
COPY backend/core ./core
COPY backend/providers ./providers
COPY backend/worker.py ./worker.py
COPY contracts /app/contracts
COPY supabase/migrations /app/supabase/migrations

ENV CONTRACTS_DIR=/app/contracts \
    PATH=/app/backend/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
