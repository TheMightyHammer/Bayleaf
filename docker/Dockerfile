# ForagedApp Docker image
# - Uses a small Python base image
# - Installs pinned dependencies from requirements.txt
# - Runs FastAPI via uvicorn

FROM python:3.12-slim

# Prevent Python from writing .pyc files and force stdout/stderr to be unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (kept minimal). curl is handy for basic container health checks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first to leverage Docker layer caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy application code
COPY app /app/app

# Create a non-root user for running the app
RUN useradd -m -u 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Default runtime configuration (can be overridden in docker-compose.yml)
ENV FORAGED_HOST=0.0.0.0 \
    FORAGED_PORT=8000 \
    FORAGED_ENV=prod

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]