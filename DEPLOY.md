# Развёртывание на VPS (Docker)

Краткая инструкция без предположений об опыте в DevOps. Цель: бот круглосуточно в Docker, SQLite на постоянном томе, Chromium внутри образа для Mashina/Lalafo.

## Что понадобится

- VPS с **Ubuntu 22.04 LTS** (или новее), **от 2 GB RAM** (для Chromium надёжнее **4 GB**).
- SSH-доступ под `root` или пользователем с `sudo`.
- В этом репозитории в коммит включён **тестовый `.env`** (удобно для `git clone` на VPS без `scp`). Для **продакшена** замените токены/ключи на свои и **не публикуйте** боевой `.env` в открытый git. Образец полей: [.env.example](.env.example).

## 0. Последовательность на сервере (кратко)

Репозиторий: `https://github.com/timyrdoc13-alt/Car_bot.git` (каталог после клона обычно **`Car_bot`**).

1. Установите **Docker** — раздел **«1. Установка Docker»** ниже (от `root` можно без `sudo`).
2. Если раньше клон падал и папка битая: `rm -rf ~/Car_bot`
3. Клон (публичный репозиторий — **без токена**):
   ```bash
   cd ~
   git clone https://github.com/timyrdoc13-alt/Car_bot.git
   cd Car_bot
   ```
   **Не вставляйте** строку вида `github_pat_...` **отдельной строкой** в терминал: shell попытается выполнить её как команду → `command not found`. Токен используют **только** внутри URL для **приватного** репозитория и только с правами **read** на код (fine-grained: **Contents: Read**).
4. Если папка уже есть и репозиторий целый: `cd ~/Car_bot && git pull`
5. **`.env`:** после клона уже есть в `Car_bot/`; при необходимости перезапишите своим: `scp /путь/к/.env root@ВАШ_IP:~/Car_bot/.env`. На сервере: `chmod 600 ~/Car_bot/.env`
6. Запуск: `cd ~/Car_bot && docker compose up -d --build`
7. Проверка: `docker compose ps` и `docker compose logs -f bot`

Ошибка **`403` / `Write access not granted`** чаще всего из‑за **не того токена** (например без доступа к репозиторию) или попытки **push** с сервера — для развёртывания нужен только **`git clone`**/`pull` (чтение).

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
git clone https://github.com/timyrdoc13-alt/Car_bot.git
cd Car_bot
```

Скопируйте `.env` с локальной машины (пример):

```bash
scp .env root@YOUR_SERVER_IP:~/Car_bot/.env
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
cd ~/Car_bot
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

Или найти том и скопировать файл через `docker volume inspect` (имя вида `Car_bot_bot_data`, зависит от каталога с `docker-compose.yml`).

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
