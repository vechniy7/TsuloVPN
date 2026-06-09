# TsuloVPN — Telegram-бот с рабочими бесплатными VPN-ключами

Бот выдаёт **одну ссылку подписки** для Hiddify, Happ, v2rayNG и других клиентов. Внутри — ~32 проверенных сервера:

- **25 обычных VPN** — из рекомендованных списков [goida-vpn-configs](https://github.com/AvenCores/goida-vpn-configs)
- **7 серверов обхода белых списков** — из `26.txt`

Нерабочие ключи отсеиваются TCP-проверкой. При обновлении подписки в приложении список заменяется на актуальный.

## Быстрый старт

```bash
cd TsuloVPN
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy src\.env.example src\.env  # заполните BOT_TOKEN, ADMINS, SUBSCRIPTION_PUBLIC_URL
cd src
python app.py
```

## Настройка `.env`

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | Токен от @BotFather |
| `ADMINS` | Telegram ID админов через запятую |
| `SUBSCRIPTION_PUBLIC_URL` | Публичный HTTPS-URL (например `https://vpn.example.com`) |
| `SUBSCRIPTION_PORT` | Локальный порт HTTP-сервера подписок (по умолчанию `8080`) |

## HTTPS (обязательно для Hiddify / Happ)

Проксируйте порт `SUBSCRIPTION_PORT` через nginx или Caddy:

```nginx
server {
    listen 443 ssl;
    server_name vpn.example.com;

    ssl_certificate     /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
    }
}
```

В `.env` укажите: `SUBSCRIPTION_PUBLIC_URL=https://vpn.example.com`

## Как это работает

1. Бот регистрирует пользователя и выдаёт уникальную ссылку: `https://ваш-домен/sub/{token}`
2. Фоновая задача каждые ~10 минут:
   - скачивает конфиги из goida-vpn-configs
   - проверяет доступность host:port
   - формирует пул из 25 + 7 самых быстрых рабочих серверов
3. Hiddify / Happ по этой ссылке получает TXT-подписку (по одному URI на строку)
4. При обновлении подписки в приложении — мёртвые серверы исчезают, появляются новые рабочие

## Команды бота

- `/start` — регистрация и меню
- `/key` — получить ссылку подписки и QR-код
- `/help` — инструкция для Hiddify / Happ
- `/menu` — главное меню

## Структура

```
TsuloVPN/
├── src/
│   ├── app.py                 # Telegram-бот + HTTP-сервер подписок
│   ├── config_pool.py         # Загрузка goida + health-check
│   ├── subscription_server.py # GET /sub/{token}
│   ├── handlers.py            # Команды бота
│   └── parser.py              # Парсинг и фильтрация конфигов
├── requirements.txt
└── README.md
```

## Важно

- Это **публичные бесплатные прокси** — без гарантий приватности и скорости
- TCP-проверка подтверждает доступность порта, но не полный VPN-handshake
- Для продакшена нужен VPS с публичным HTTPS-доменом
