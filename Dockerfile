# arm64 to match Fargate Graviton -- cheaper to run and builds natively on Apple Silicon.
FROM --platform=linux/arm64 python:3.13-slim

# Unbuffered so CloudWatch shows progress live rather than in bursts when a buffer
# flushes. On a six-hour job that is the difference between watching it and guessing.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# Nothing here needs root. data/ is pre-created and owned by the runner so that a
# container started without RAW_URI still works -- otherwise every write fails with a
# permission error and the run burns requests producing nothing. In production RAW_URI
# points at S3 and this directory stays empty.
RUN useradd --create-home --uid 10001 runner \
    && mkdir -p /app/data/raw \
    && chown -R runner:runner /app/data
USER runner

# Defaults are deliberately conservative. Override them in the task definition rather
# than rebuilding the image -- the whole point of the brakes is changing limits without
# a redeploy.
ENTRYPOINT ["python", "src/backfill.py"]
CMD ["--start", "1920", "--end", "2025", "--delay", "0.5", "--max-hours", "8"]
