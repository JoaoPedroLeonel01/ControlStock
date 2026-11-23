FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered standard I/O
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY src/ ./src/

# Expose default port
EXPOSE 8000

# Run FastAPI with Uvicorn, dynamically respecting $PORT if provided by the cloud platform
CMD ["sh", "-c", "uvicorn src.control_stock.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
