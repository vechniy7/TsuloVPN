/**
 * Telegram webhook + проверка подписки на канал (edge).
 * Amvera не может вызвать api.telegram.org — поэтому gate здесь.
 *
 * Env (Pages → Settings → Environment variables / Secrets):
 *   BOT_TOKEN=...
 *   REQUIRED_CHANNEL=@TsuloVPN
 *   CHANNEL_URL=https://t.me/TsuloVPN
 *   ADMINS=123,456
 *   AMVERA_ORIGIN=https://tsulovpn-culoebali.amvera.io
 *   CHANNEL_GATE_ENABLED=true
 */
const DEFAULT_ORIGIN = "https://tsulovpn-culoebali.amvera.io";
const CHECK_CB = "check_channel_sub";

function originBase(env) {
  return String((env && env.AMVERA_ORIGIN) || DEFAULT_ORIGIN).replace(/\/$/, "");
}

function channelId(env) {
  return String((env && env.REQUIRED_CHANNEL) || "@TsuloVPN").trim();
}

function channelUrl(env) {
  return String((env && env.CHANNEL_URL) || "https://t.me/TsuloVPN").trim();
}

function adminSet(env) {
  const raw = String((env && env.ADMINS) || "");
  return new Set(
    raw
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean)
      .map((x) => Number(x))
      .filter((n) => Number.isFinite(n)),
  );
}

function gateEnabled(env) {
  const v = String((env && env.CHANNEL_GATE_ENABLED) || "true").toLowerCase();
  return v === "1" || v === "true" || v === "yes";
}

function extractUser(update) {
  if (update.message && update.message.from) {
    return {
      user: update.message.from,
      chatId: update.message.chat.id,
      kind: "message",
      callbackId: null,
      data: null,
      messageId: update.message.message_id,
    };
  }
  if (update.callback_query && update.callback_query.from) {
    const cq = update.callback_query;
    return {
      user: cq.from,
      chatId: cq.message ? cq.message.chat.id : cq.from.id,
      kind: "callback",
      callbackId: cq.id,
      data: cq.data || "",
      messageId: cq.message ? cq.message.message_id : null,
    };
  }
  return null;
}

async function tgApi(token, method, body) {
  const res = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

async function isMember(token, channel, userId) {
  try {
    const data = await tgApi(token, "getChatMember", {
      chat_id: channel,
      user_id: userId,
    });
    if (!data.ok) return false;
    const status = data.result && data.result.status;
    if (status === "restricted") return Boolean(data.result.is_member);
    return status === "member" || status === "administrator" || status === "creator";
  } catch (_) {
    // При сбое API не блокируем навсегда — пускаем дальше.
    return true;
  }
}

function subscribeKeyboard(env) {
  return {
    inline_keyboard: [
      [{ text: "📢 Подписаться на канал", url: channelUrl(env) }],
      [{ text: "✅ Проверить подписку", callback_data: CHECK_CB }],
    ],
  };
}

function subscribeText(env) {
  const ch = channelId(env).replace(/^@/, "");
  return (
    `<b>TsuloVPN</b> · доступ\n\n` +
    `Чтобы пользоваться ботом, подпишитесь на канал <b>@${ch}</b>.\n\n` +
    `1. Нажмите «Подписаться на канал»\n` +
    `2. Вернитесь и нажмите «Проверить подписку»`
  );
}

async function replyBlocked(token, ctx, env) {
  const text = subscribeText(env);
  const markup = subscribeKeyboard(env);
  if (ctx.kind === "callback" && ctx.callbackId) {
    await tgApi(token, "answerCallbackQuery", {
      callback_query_id: ctx.callbackId,
      text: "Сначала подпишитесь на канал",
      show_alert: true,
    });
    if (ctx.messageId) {
      await tgApi(token, "editMessageText", {
        chat_id: ctx.chatId,
        message_id: ctx.messageId,
        text,
        parse_mode: "HTML",
        reply_markup: markup,
        disable_web_page_preview: true,
      });
      return;
    }
  }
  await tgApi(token, "sendMessage", {
    chat_id: ctx.chatId,
    text,
    parse_mode: "HTML",
    reply_markup: markup,
    disable_web_page_preview: true,
  });
}

async function forwardToAmvera(request, env, bodyBuf) {
  const amvera = `${originBase(env)}/telegram/webhook`;
  const upstream = await fetch(amvera, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: bodyBuf,
  });
  const text = await upstream.text();
  let payload = null;
  try {
    payload = JSON.parse(text);
  } catch (_) {
    payload = null;
  }

  const token = (env.BOT_TOKEN || "").trim();
  // Amvera может вернуть пачку методов — Cloudflare исполняет их сам
  // (иначе из webhook-ответа уходит только один, и callback «висит»).
  if (token && payload && Array.isArray(payload.methods) && payload.methods.length) {
    for (const item of payload.methods) {
      if (!item || typeof item !== "object") continue;
      const method = item.method;
      if (!method || typeof method !== "string") continue;
      const body = { ...item };
      delete body.method;
      try {
        await tgApi(token, method, body);
      } catch (err) {
        console.log("tg method failed", method, String(err));
      }
    }
    return Response.json({
      ok: true,
      via: "cf-multi",
      count: payload.methods.length,
    });
  }

  return new Response(text, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") || "application/json",
      "X-Tsulo-Edge": "tg-webhook",
    },
  });
}

export async function onRequest(context) {
  const { request, env } = context;

  if (request.method === "GET") {
    return Response.json({
      ok: true,
      relay: "telegram-webhook+channel-gate",
      channel: channelId(env),
      gate: gateEnabled(env),
      has_token: Boolean(env.BOT_TOKEN),
    });
  }

  if (request.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }

  const bodyBuf = await request.arrayBuffer();
  const token = (env.BOT_TOKEN || "").trim();

  // Всегда пробуем Amvera; multi-method исполняем в forwardToAmvera при наличии BOT_TOKEN.
  if (!token || !gateEnabled(env)) {
    return forwardToAmvera(request, env, bodyBuf);
  }

  let update;
  try {
    update = JSON.parse(new TextDecoder().decode(bodyBuf));
  } catch (_) {
    return forwardToAmvera(request, env, bodyBuf);
  }

  const ctx = extractUser(update);
  if (!ctx) {
    return forwardToAmvera(request, env, bodyBuf);
  }

  const admins = adminSet(env);
  if (admins.has(Number(ctx.user.id))) {
    return forwardToAmvera(request, env, bodyBuf);
  }

  const member = await isMember(token, channelId(env), ctx.user.id);

  if (ctx.kind === "callback" && ctx.data === CHECK_CB) {
    if (member) {
      await tgApi(token, "answerCallbackQuery", {
        callback_query_id: ctx.callbackId,
        text: "Подписка подтверждена ✓",
        show_alert: true,
      });
      return forwardToAmvera(request, env, bodyBuf);
    }
    await replyBlocked(token, ctx, env);
    return Response.json({ ok: true, gated: true });
  }

  if (!member) {
    await replyBlocked(token, ctx, env);
    return Response.json({ ok: true, gated: true });
  }

  return forwardToAmvera(request, env, bodyBuf);
}
