FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Dependencies first (cached layer)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project

# Application code and seed data
COPY src/ ./src/
COPY seed/ ./seed/
RUN uv sync --locked

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "--factory", "sec_reports.main:build_app", "--host", "0.0.0.0", "--port", "8000"]
