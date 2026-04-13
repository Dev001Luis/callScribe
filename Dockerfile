FROM python:3.11-slim

# Install system dependencies for faster-whisper and audio
RUN apt-get update && apt-get install -y \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install gunicorn eventlet

COPY . .

# Render uses the $PORT environment variable
CMD gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:$PORT --timeout 0 app:app