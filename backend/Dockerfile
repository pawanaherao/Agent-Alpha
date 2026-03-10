# Use Python 3.12 Slim as base image (REQUIRED for numba compatibility)
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies (simplified - no TA-Lib compilation needed)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install build dependencies first (helps with numba compilation)
RUN pip install --no-cache-dir setuptools wheel

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Expose port 8000 (aligned with docker-compose and src/main.py)
EXPOSE 8000

# Start the application (entrypoint is src.main:app on port 8000)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
