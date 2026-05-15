FROM python:3.11-slim

WORKDIR /app

# System deps: ffmpeg for audio extraction, git for vault sync
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer-cached unless requirements.txt changes)
# openai-whisper and sentence-transformers are optional (disabled by default config)
# and are excluded here to keep the image lean and avoid build issues.
COPY requirements.txt .
RUN pip install --upgrade pip setuptools \
    && grep -vE "^\s*(openai-whisper|sentence-transformers)" requirements.txt \
       | pip install --no-cache-dir -r /dev/stdin

# Copy application code
COPY . .

RUN chmod +x scripts/entrypoint.sh

ENTRYPOINT ["scripts/entrypoint.sh"]
