# System Monitor - Multi-stage build
FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final image
FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies for psutil and sensors
RUN apt-get update && apt-get install -y --no-install-recommends \
    lm-sensors \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Copy Python packages from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY src/ ./src/

# Create directories for config and data
RUN mkdir -p /config /data

# Default environment variables
ENV SYSMON_MODE=client \
    SYSMON_CONFIG_PATH=/config/config.yaml \
    SYSMON_DB_PATH=/data/system_monitor.db \
    PYTHONUNBUFFERED=1

# Health check (only relevant for server mode)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/health', timeout=5)" || exit 1

# Expose server port
EXPOSE 8080

# Run the application
CMD ["python", "-m", "src.main"]

