FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered standard I/O
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and database migrations
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini .

# Run as an unprivileged user
RUN useradd --create-home --uid 1000 appuser
USER appuser

# Expose default port
EXPOSE 8000

# Apply pending migrations, then run FastAPI with Uvicorn on $PORT.
# Render's free plan has no Pre-Deploy Command, so migrations run at container
# start: if they fail, the container exits and the API never starts.
# "exec" makes Uvicorn PID 1, so it receives the platform's stop signal.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn src.control_stock.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
