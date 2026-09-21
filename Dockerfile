# FastAPI runtime. backend/ is the canonical Python service for the v2 rewrite.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app/backend

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend ./

ENV LAB_ENVIRONMENT=prod
ENV LAB_ENABLE_WORKERS=true
EXPOSE 8000
CMD ["uv", "run", "--no-dev", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
