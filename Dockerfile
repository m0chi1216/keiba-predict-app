FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 PYTHONDONTWRITEBYTECODE=1 \
    CHROME_BINARY=/usr/bin/chromium SE_CHROMEDRIVER=/usr/bin/chromedriver \
    CHROME_NO_SANDBOX=true OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2

RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium chromium-driver libgomp1 fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser . .
RUN mkdir -p data/webapp && chown appuser:appuser data/webapp
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
CMD ["python", "-m", "apps.race_predict.server", "--host", "0.0.0.0", "--port", "8000"]
