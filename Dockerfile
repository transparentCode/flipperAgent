FROM ghcr.io/astral-sh/uv:0.12.11 AS uv

# Note: Using Python 3.13 to align with pyproject.toml requires-python = ">=3.12"
FROM python:3.13-slim AS builder

WORKDIR /app

# Copy the project metadata and generated lock for reproducible dependency sync.
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./

# The image executes copied source through PYTHONPATH, so only the locked
# third-party environment is installed at the same absolute path used by the
# runtime image so console-script shebangs remain valid after the copy.
RUN uv sync --locked --no-install-project --no-dev

FROM python:3.13-slim

WORKDIR /app

# Add non-root user and prepare data and logs directories with correct ownership
RUN groupadd -r flipper && useradd -r -g flipper flipper \
    && mkdir -p /app/data /app/logs && chown -R flipper:flipper /app

# Copy the locked virtual environment.
COPY --from=builder --chown=flipper:flipper /app/.venv /app/.venv

# Finally, copy the actual source code with correct ownership
COPY --chown=flipper:flipper ./src /app/src
COPY --chown=flipper:flipper ./configs /app/configs

USER flipper
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app/src
ENV NUMBA_CACHE_DIR=/tmp/numba_cache

CMD ["python"]
