# App image: the REST API (icos_maps.api), which also builds the maps nightly and on request and
# publishes the site to a shared volume; nginx serves that volume and proxies /api (compose.yml).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
# rasterio's bundled GDAL needs libexpat, which the slim image lacks.
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*

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

EXPOSE 8000
CMD ["icos-maps-api"]
