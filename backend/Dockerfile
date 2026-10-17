FROM python:3.12.7-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY knowledge ./knowledge
COPY tools ./tools
COPY tests ./tests

# непривилегированный пользователь; данные (ключ dev-режима, бэкапы) — в томе
RUN useradd --create-home --uid 10001 kompas && mkdir -p /app/data && chown -R kompas /app/data
USER kompas

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS:-4} --proxy-headers --log-level warning"]
