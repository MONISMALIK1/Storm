# ── Build stage ─────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements-pipeline.txt .

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements-pipeline.txt


# ── Runtime stage ────────────────────────────────────────────────
FROM python:3.12-slim

# Create a non-root user
RUN useradd -m -s /bin/bash storm

WORKDIR /opt/storm

# Copy installed packages from build stage
COPY --from=builder /install /usr/local

# Copy application code (excludes paths in .dockerignore)
COPY --chown=storm:storm . .

# The database lives on a mounted volume — never bake it into the image
VOLUME ["/opt/storm/data"]

# The INTEL_DB_PATH will be set to /opt/storm/data/intel.db by docker-compose
ENV INTEL_DB_PATH=/opt/storm/data/intel.db \
    INTEL_ENV=production \
    PYTHONUNBUFFERED=1

# FastAPI listens internally on 8000; Nginx or a load balancer sits in front
EXPOSE 8000

USER storm

# Healthcheck so Docker/compose knows when the API is ready
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "-m", "uvicorn", "intel.api:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--no-access-log"]
