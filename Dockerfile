FROM python:3.14-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY src/ ./src/
COPY seed/ ./seed/
COPY admin/ ./admin/

EXPOSE 8080

CMD ["uv", "run", "python", "-m", "connector_app.server"]
