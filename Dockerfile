FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY handbook ./handbook

RUN uv sync --frozen --no-dev

ENV MARLOW_LLM=""
ENV MARLOW_WEB_HOST=0.0.0.0
ENV MARLOW_WEB_PORT=8000
ENV MARLOW_DATABASE_URL=sqlite:////data/marlow.db
ENV MARLOW_CHROMA_DIR=/chroma
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uv", "run", "--no-dev", "python", "-m", "marlow.web", "--host", "0.0.0.0", "--port", "8000"]
