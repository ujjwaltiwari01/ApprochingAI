# API container — Python 3.11 slim keeps image smaller than full Playwright base.
# Render sets $PORT; uvicorn binds 0.0.0.0 for health checks and GitHub Actions POSTs.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs

EXPOSE 8000

CMD uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000}
