/**
 * Постоянный релей без webhook на Amvera.
 * Cloudflare Cron каждую минуту:
 *  1) getUpdates у Telegram
 *  2) POST апдейта на Amvera
 *  3) выполняет method из ответа (sendMessage и т.п.)
 *
 * Нужны:
 *  - secret BOT_TOKEN
 *  - KV binding OFFSETS (ключ "telegram_offset")
 */
const AMVERA_DEFAULT =
  "https://tsulovpn-culoebali.amvera.io/telegram/webhook";

async function tg(token, method, payload) {
  const res = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload ?? {}),
  });
  return res.json();
}

async function processUpdate(env, update) {
  const amvera = env.AMVERA_WEBHOOK_URL || AMVERA_DEFAULT;
  const upstream = await fetch(amvera, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(update),
  });
  const text = await upstream.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    return { ok: false, error: `amvera non-json ${upstream.status}` };
  }
  const method = body.method;
  if (!method) {
    return { ok: true, note: "no method", status: upstream.status };
  }
  const payload = { ...body };
  delete payload.method;
  const result = await tg(env.BOT_TOKEN, method, payload);
  return { ok: !!result.ok, method, result };
}

async function pollOnce(env) {
  if (!env.BOT_TOKEN) {
    return { ok: false, error: "BOT_TOKEN secret missing" };
  }
  if (!env.OFFSETS) {
    return { ok: false, error: "OFFSETS KV missing" };
  }

  // Webhook мешает getUpdates — снимаем один раз.
  const flag = await env.OFFSETS.get("webhook_cleared");
  if (flag !== "1") {
    await tg(env.BOT_TOKEN, "deleteWebhook", { drop_pending_updates: false });
    await env.OFFSETS.put("webhook_cleared", "1");
  }

  const rawOffset = await env.OFFSETS.get("telegram_offset");
  const offset = rawOffset ? Number(rawOffset) : undefined;
  const updatesResp = await tg(env.BOT_TOKEN, "getUpdates", {
    timeout: 0,
    offset: Number.isFinite(offset) ? offset : undefined,
    allowed_updates: ["message", "callback_query"],
    limit: 50,
  });
  if (!updatesResp.ok) {
    return { ok: false, error: updatesResp };
  }
  const updates = updatesResp.result || [];
  const results = [];
  for (const update of updates) {
    const out = await processUpdate(env, update);
    results.push({ update_id: update.update_id, ...out });
    await env.OFFSETS.put("telegram_offset", String(update.update_id + 1));
  }
  return { ok: true, processed: updates.length, results };
}

export default {
  async scheduled(event, env, ctx) {
    const result = await pollOnce(env);
    console.log("poll", JSON.stringify(result));
    return result;
  },

  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/run" || url.pathname === "/poll") {
      const secret = url.searchParams.get("key") || "";
      if (env.RUN_KEY && secret !== env.RUN_KEY) {
        return Response.json({ ok: false, error: "forbidden" }, { status: 403 });
      }
      const result = await pollOnce(env);
      return Response.json(result);
    }
    return Response.json({
      ok: true,
      mode: "cron-poll",
      hint: "GET /run?key=... to poll now",
    });
  },
};
