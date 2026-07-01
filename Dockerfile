FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

COPY . .

RUN uv sync --frozen --no-dev

EXPOSE 7777

CMD ["uv", "run", "-m", "dynamic_agent_service"]
