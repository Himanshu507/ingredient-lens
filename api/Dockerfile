FROM python:3.11-slim
WORKDIR /app

RUN pip install --no-cache-dir uv
ENV UV_NO_SYNC=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY config.py run_pipeline.py alembic.ini ./
COPY db ./db
COPY pipeline ./pipeline
COPY api ./api

CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn api.main:app --host 0.0.0.0 --port 8000"]
