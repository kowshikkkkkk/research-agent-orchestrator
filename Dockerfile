# Dockerfile
# Single image used by all our agent services.
# Each service runs a different command but uses the same codebase.
# This is the production pattern — one image, multiple services.

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for Docker layer caching
# If requirements don't change, this layer is cached
# and pip install doesn't re-run on every build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application code
COPY . .

# Default command — overridden per service in docker-compose.yml
CMD ["python", "-m", "orchestrator.orchestrator"]