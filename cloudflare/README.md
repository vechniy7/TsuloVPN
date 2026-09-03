# Публичный edge TsuloVPN (Cloudflare Pages)

Amvera часто плохо открывается с мобильного интернета и при включённом VPN.
Пользователи, Happ и кабинет ходят на **Cloudflare**, а Pages прозрачно
проксирует запросы на Amvera.

## Боевой URL

```
https://tsulo-tg-relay.pages.dev
```

Примеры:

| Что | URL |
|-----|-----|
| Edge health | `https://tsulo-tg-relay.pages.dev/_edge` |
| Тарифы | `https://tsulo-tg-relay.pages.dev/tariffs` |
| Кабинет | `https://tsulo-tg-relay.pages.dev/miniapp` |
| Подписка Happ | `https://tsulo-tg-relay.pages.dev/sub/<token>` |
| Telegram webhook | `https://tsulo-tg-relay.pages.dev/telegram/webhook` |
| Platega webhook | `https://tsulo-tg-relay.pages.dev/platega/webhook` |

## Amvera env (обязательно)

```
SUBSCRIPTION_PUBLIC_URL=https://tsulo-tg-relay.pages.dev
```

После смены URL:

1. Дождитесь редеплоя Amvera.
2. В боте заново откройте «Мой доступ» (старые ключи могли указывать на amvera.io).
3. В кабинете Platega обновите callback на  
   `https://tsulo-tg-relay.pages.dev/platega/webhook`
4. Telegram webhook уже на этом же хосте (GitHub Action / setWebhook).

## Деплой Pages

```bash
cd cloudflare/pages
npx wrangler pages deploy public --project-name=tsulo-tg-relay --commit-dirty=true
```

Переменная origin (по умолчанию уже в `wrangler.toml`):

```
AMVERA_ORIGIN=https://tsulovpn-culoebali.amvera.io
```

## Важно

- `*.workers.dev` в этом аккаунте с битым SSL — **не использовать** для Happ.
- Origin Amvera не светим пользователям: в боте только `pages.dev` (или свой домен на CF).
- Свой домен: Cloudflare Pages → Custom domains → DNS → тот же проект.
