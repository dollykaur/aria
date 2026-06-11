FROM python:3.11-slim

WORKDIR /app

RUN pip install uv

COPY pyproject.toml ./
RUN uv sync --no-dev

COPY aria/ ./aria/

CMD ["uv", "run", "aria"]
