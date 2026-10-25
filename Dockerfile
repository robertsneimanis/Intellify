# Ingest service image. Built and run by docker-compose.yml (service `ingest`).
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && useradd --system --no-create-home ingest

USER ingest
ENV PYTHONUNBUFFERED=1
# SIGTERM from `docker stop` is handled as a clean shutdown.
CMD ["python", "-m", "ingest"]
