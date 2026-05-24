# Note: Using Python 3.13 to align with pyproject.toml requires-python = ">=3.13"
FROM python:3.13-slim AS builder

WORKDIR /build

# Copy only pyproject.toml and README needed for initial dependency install
COPY pyproject.toml README.md ./

# Create dummy src to allow pip wheel to succeed for third-party dependencies caching
RUN mkdir -p src/apps src/libs && touch src/apps/__init__.py src/libs/__init__.py \
    && pip wheel --no-cache-dir --wheel-dir /build/wheels .

FROM python:3.13-slim

WORKDIR /app

# Add non-root user and prepare data directory
RUN groupadd -r flipper && useradd -r -g flipper flipper \
    && mkdir -p /app/data && chown -R flipper:flipper /app

# Copy the built wheels and install them
COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Finally, copy the actual source code with correct ownership
COPY --chown=flipper:flipper ./src /app/src
COPY --chown=flipper:flipper ./configs /app/configs

USER flipper
ENV PYTHONPATH=/app/src

CMD ["python"]
