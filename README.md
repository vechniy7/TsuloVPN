# TsuloVPN — Telegram-бот с бесплатными VPN-ключами

Бот выдаёт **одну ссылку подписки** для Hiddify, Happ, v2rayNG и других клиентов:

- **20 обычных VPN** — для WiFi и обычного интернета
- **15 серверов обхода белых списков** — для мобильного интернета (Мегафон, МТС и др.)

При обновлении подписки в приложении список заменяется на актуальный.

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
| `CONFIG_RAW_BASE` | URL источника RAW-конфигов |

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

## Команды бота

- `/start` — регистрация и меню
- `/key` — получить ссылку подписки и QR-код
- `/help` — инструкция для Hiddify / Happ
- `/menu` — главное меню

## Структура

```
TsuloVPN/
├── src/
│   ├── app.py
│   ├── config_pool.py
│   ├── subscription_server.py
│   ├── handlers.py
│   └── parser.py
├── requirements.txt
└── README.md
```
