FROM python:3.11-slim

WORKDIR /app

# System deps: ffmpeg for audio extraction, git for vault sync
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer-cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir \
        pyyaml python-dotenv pydantic \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

RUN chmod +x scripts/entrypoint.sh

ENTRYPOINT ["scripts/entrypoint.sh"]
