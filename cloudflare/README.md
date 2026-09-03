# Постоянный Telegram-релей (без ПК)

Amvera недоступна для серверов Telegram (`Connection timed out`),
поэтому webhook смотрит на Cloudflare Pages, а Pages проксирует на Amvera.

## Боевой URL

```
https://tsulo-tg-relay.pages.dev/telegram/webhook
```

Цепочка: **Telegram → Cloudflare Pages → Amvera → sendMessage в ответе webhook**.

## Деплой / обновление функции

```bash
cd cloudflare/pages
npx wrangler pages deploy public --project-name=tsulo-tg-relay --commit-dirty=true
```

Функция лежит в `functions/telegram/webhook.js`.

## Переустановка webhook

```bash
curl -X POST "https://api.telegram.org/bot$BOT_TOKEN/setWebhook" \
  --data-urlencode "url=https://tsulo-tg-relay.pages.dev/telegram/webhook" \
  --data-urlencode "drop_pending_updates=true" \
  --data-urlencode 'allowed_updates=["message","callback_query"]'
```

Проверка:

```bash
curl "https://api.telegram.org/bot$BOT_TOKEN/getWebhookInfo"
```

Не должно быть `last_error_message`.

## Важно

- Локальный `scripts/telegram_bridge.py` больше не нужен (только аварийный запас).
- Worker `*.workers.dev` в этом аккаунте имеет битый SSL — не использовать для webhook.
- Cron-poll на Worker отключён (конфликтует с webhook).
