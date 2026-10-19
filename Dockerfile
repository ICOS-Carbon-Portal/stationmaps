# Builder image: runs `icos-maps` on a schedule and publishes the site to a shared volume
# (see docker/builder.sh); nginx serves that volume (compose.yml).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.20 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    MPLCONFIGDIR=/tmp/matplotlib \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY assets ./assets
COPY web ./web
RUN uv sync --frozen --no-dev

COPY docker/builder.sh /usr/local/bin/builder.sh
CMD ["builder.sh"]
