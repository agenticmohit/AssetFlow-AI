FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY assetflow ./assetflow
COPY templates ./templates
COPY static ./static

RUN useradd --create-home --uid 10001 assetflow \
    && mkdir -p /app/var/uploads /data \
    && chown -R assetflow:assetflow /app /data

USER assetflow
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn assetflow.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WEB_CONCURRENCY:-1}"]
