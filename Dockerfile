# Образ бота + опционально веб-монитор (FastAPI). Chromium нужен для Mashina/Lalafo.
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Минимальный слой до копирования кода — кэш при изменении только приложения
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY car_channel_bot ./car_channel_bot

# Зависимости приложения и веб-монитора, затем браузер Playwright (тяжёлый слой)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir ".[monitoring,queue]" \
    && playwright install --with-deps chromium \
    && rm -rf /root/.cache/pip

CMD ["car-bot"]
