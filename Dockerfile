FROM python:3.11-slim

# Install ffmpeg dan library sistem untuk Voice Chat audio
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Command akan di-override per service di Railway
CMD ["python", "hans_concierge/main.py"]
