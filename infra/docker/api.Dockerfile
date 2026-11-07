FROM python:3.12-slim AS runner

# Create non-root user
RUN groupadd -r querylens && useradd -r -g querylens -m -d /home/querylens querylens

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies from lock
COPY apps/api/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock

# Copy API application code
COPY apps/api/pyproject.toml /app/pyproject.toml
COPY apps/api/src /app/src
RUN pip install --no-cache-dir --no-deps -e .

USER querylens

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD curl -f http://127.0.0.1:8000/api/v1/health/live || exit 1

CMD ["uvicorn", "querylens.main:app", "--host", "0.0.0.0", "--port", "8000"]
