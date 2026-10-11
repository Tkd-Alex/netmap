FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TZ=Europe/Rome
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --create-home --uid 10001 netmap \
    && mkdir /data && chown netmap /data

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app.py ./
COPY templates ./templates
COPY deploy/healthcheck.py ./healthcheck.py

# Database, names and meta live in the /data volume
ENV DB_PATH=/data/network.db NAMES_FILE=/data/names.json META_FILE=/data/meta.json
VOLUME /data
USER netmap
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=5s --start-period=60s --retries=3 CMD ["python", "healthcheck.py"]
# A SINGLE process: polling lives in a thread
CMD ["waitress-serve", "--listen=0.0.0.0:8080", "--threads=4", "app:app"]
