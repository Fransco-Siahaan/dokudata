# API and worker image (same image, different command).
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DOKUDATA_OCR_THREADS=2 HF_HOME=/opt/hf
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-ind tesseract-ocr-eng libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml README.md ./
COPY pipeline ./pipeline
COPY ml ./ml
RUN pip install ".[api]"
COPY apps/api ./apps/api
COPY config ./config
COPY models ./models
COPY reports/latest ./reports/latest
# Warm the OCR models into the image so the first request is not slow.
RUN python -c "from pipeline.ocr import RapidOCREngine; RapidOCREngine()" && chown -R app /app
USER app
ENV PYTHONPATH=/app:/app/apps
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fs http://localhost:8000/api/v1/health || exit 1
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
