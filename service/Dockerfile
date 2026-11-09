# Build from the repository root:  docker build -f service/Dockerfile -t command-parser:1.0.0 .
# CPU-only torch wheels (no CUDA libraries). No model weights: they are downloaded from object storage at start-up.
FROM python:3.11.9-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv

COPY service/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && rm -rf /root/.cache

COPY service/app /srv/app
COPY data/schema.json /srv/app/schema.json

RUN useradd --system --uid 10001 parser && mkdir -p /tmp/model && chown parser /tmp/model
USER 10001

EXPOSE 8000
CMD ["uvicorn", "app.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
