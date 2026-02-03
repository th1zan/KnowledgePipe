# Weekly Digest Orchestrator - Dockerfile
# Multi-stage build for smaller production image

# =============================================================================
# Stage 1: Build dependencies
# =============================================================================
FROM python:3.11-slim as builder

WORKDIR /app

# Install Poetry
RUN pip install --no-cache-dir poetry==1.7.1

# Copy only dependency files first for better caching
COPY pyproject.toml poetry.lock* ./

# Configure Poetry to not create virtualenv (we're in a container)
RUN poetry config virtualenvs.create false

# Install dependencies only (no project yet)
RUN poetry install --no-interaction --no-ansi --no-root --only main

# =============================================================================
# Stage 2: Production image
# =============================================================================
FROM python:3.11-slim as production

WORKDIR /app

# Create non-root user for security
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY src/ ./src/

# Create directories for data and audio
RUN mkdir -p /data /audio && \
    chown -R appuser:appgroup /app /data /audio

# Switch to non-root user
USER appuser

# Environment variables with defaults
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    # Application defaults
    DATABASE_PATH=/data/state.db \
    AUDIO_LOCAL_PATH=/audio \
    API_PORT=8002 \
    LOG_LEVEL=INFO \
    LOG_FORMAT=json

# Expose API port
EXPOSE 8002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8002/health', timeout=5).raise_for_status()" || exit 1

# Default command - run the FastAPI application
CMD ["python", "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8002"]
