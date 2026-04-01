FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    openssh-client \
    sshpass \
    rsync \
    nginx \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (for code validation)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g pm2

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright
RUN pip install playwright && playwright install chromium --with-deps

# Copy application code
COPY . .

# Create workspace directories
RUN mkdir -p /root/workspace /root/workspace/screenshots

# Expose port
EXPOSE 8900

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8900/api/health || exit 1

# Start
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8900", "--workers", "1"]
