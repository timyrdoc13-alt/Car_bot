# Развёртывание на VPS (Docker)

Краткая инструкция без предположений об опыте в DevOps. Цель: бот круглосуточно в Docker, SQLite на постоянном томе, Chromium внутри образа для Mashina/Lalafo.

## Что понадобится

- VPS с **Ubuntu 22.04 LTS** (или новее), **от 2 GB RAM** (для Chromium надёжнее **4 GB**).
- SSH-доступ под `root` или пользователем с `sudo`.
- Файл **`.env`** с секретами (не коммитить). Образец: [.env.example](.env.example).

## 1. Установка Docker на Ubuntu

Выполните на сервере:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${VERSION_CODENAME:-jammy}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Проверка:

```bash
sudo docker run --rm hello-world
```

По желанию добавьте пользователя в группу `docker`, чтобы не писать `sudo` перед `docker`:

```bash
sudo usermod -aG docker "$USER"
```

(Выйдите из SSH и зайдите снова.)

## 2. Код и секреты на сервере

```bash
git clone <url-репозитория> car-channel-bot
cd car-channel-bot
```

Скопируйте `.env` с локальной машины (пример):

```bash
scp .env user@YOUR_SERVER_IP:~/car-channel-bot/.env
chmod 600 .env
```

Для контейнера бота путь к базе задаётся в [docker-compose.yml](docker-compose.yml) (`DATABASE_PATH=/app/data/bot.db`). Значение `DATABASE_PATH` в `.env` для режима Docker **перекрывается** переменной окружения сервиса `bot`; остальные ключи (`BOT_TOKEN`, `CHANNEL_ID`, `ADMIN_IDS`, LLM, `LISTING_SOURCE` и т.д.) читаются из `.env`.

## 3. Запуск только бота

Сборка и фоновый запуск:

```bash
docker compose up -d --build
```

Проверка:

```bash
docker compose ps
docker compose logs -f bot
```

Остановка:

```bash
docker compose down
```

Том **`bot_data`** сохраняет каталог `/app/data` с **`bot.db`** между перезапусками (`docker compose down` том **не** удаляет; удалить данные явно: `docker compose down -v` — осторожно).

## 4. Веб-монитор Mashina (опционально)

Монитор слушает **`0.0.0.0` внутри контейнера**, чтобы Uvicorn был доступен с хоста через проброс порта. На **хосте** в [docker-compose.yml](docker-compose.yml) порт привязан к **loopback**:

```yaml
ports:
  - "127.0.0.1:8765:8765"
```

Так страница **не видна из интернета** по публичному IP; зато доступна на самой машине и через **SSH-туннель**.

Запуск бота и монитора:

```bash
docker compose --profile monitor up -d --build
```

### Доступ с вашего компьютера через туннель

```bash
ssh -L 8765:127.0.0.1:8765 user@YOUR_SERVER_IP
```

Откройте в браузере: [http://127.0.0.1:8765/](http://127.0.0.1:8765/)

API `POST /api/mashina/probe`: без токена разрешён только вызов с localhost **внутри контейнера/логики проверки**; с вашего ПК через туннель задайте в `.env` **`MASHINA_MONITOR_TOKEN`** и передавайте заголовок **`X-Mashina-Monitor-Token`** (см. комментарии в [.env.example](.env.example)).

### Если нужен доступ к монитору «с интернета»

1. Не рекомендуется открывать сырой порт без **HTTPS** и ограничения доступа.
2. Осознанно смените проброс на `8765:8765` (все интерфейсы) **и** включите **UFW** / облачный firewall: закрыть всё, кроме SSH (и при необходимости 443).
3. Перед продом поставьте **Caddy/nginx** с TLS и базовой авторизацией; обязательно **`MASHINA_MONITOR_TOKEN`** для API.

## 5. Firewall (рекомендуется)

```bash
sudo ufw allow OpenSSH
sudo ufw enable
sudo ufw status
```

Порты приложения наружу не открывайте, если не используете монитор публично с reverse-proxy.

## 6. Обновление версии

```bash
cd car-channel-bot
git pull
docker compose build --no-cache
docker compose up -d
```

Если включали профиль `monitor`:

```bash
docker compose --profile monitor up -d --build
```

## 7. Резервная копия SQLite

База в именованном томе Docker. Снять копию в текущий каталог:

```bash
docker compose cp bot:/app/data/bot.db ./bot.backup.db
```

Или найти том и скопировать файл через `docker volume inspect car-channel-bot_bot_data`.

Храните бэкапы вне сервера.

## 8. Типичные проблемы

| Симптом | Что проверить |
|--------|----------------|
| Бот не отвечает | `docker compose logs bot`, токен в `.env`, один инстанс polling. |
| Нет постов в канал | Бот добавлен в канал с правом публикации; `CHANNEL_ID`. |
| Парсер падает / OOM | Больше RAM; `docker stats`; headless уже `true` в `.env`. |
| Долгая первая сборка | Нормально: слой `playwright install --with-deps chromium` тяжёлый. |

## Краткая шпаргалка

| Действие | Команда |
|----------|--------|
| Запуск бота | `docker compose up -d --build` |
| Бот + монитор | `docker compose --profile monitor up -d --build` |
| Логи | `docker compose logs -f bot` |
| Остановка | `docker compose down` |
