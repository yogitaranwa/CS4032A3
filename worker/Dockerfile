# Labelling worker and cleaner. Build from the repository root:  docker build -f worker/Dockerfile -t cca-worker:1.0.0 .
FROM python:3.11.9-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN pip install boto3==1.35.30
COPY worker /app/worker
COPY prompts /app/prompts
COPY data/commands_pool.jsonl data/schema.json /app/data/
RUN useradd --system --uid 10001 worker
USER 10001
CMD ["python", "-m", "worker.worker"]
