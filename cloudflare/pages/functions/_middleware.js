/**
 * Cloudflare Pages — публичный edge перед Amvera.
 *
 * Пользователи / Happ / Telegram WebApp / Platega ходят на:
 *   https://tsulo-tg-relay.pages.dev/...
 * Pages прозрачно проксирует на Amvera (origin скрыт, лучше проходит LTE/VPN).
 *
 * Env (Pages → Settings → Environment variables):
 *   AMVERA_ORIGIN=https://tsulovpn-culoebali.amvera.io
 */
const DEFAULT_ORIGIN = "https://tsulovpn-culoebali.amvera.io";

const SKIP_REQ = new Set([
  "host",
  "connection",
  "content-length",
  "transfer-encoding",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "upgrade",
  "cf-connecting-ip",
  "cf-ray",
  "cf-visitor",
  "cf-ipcountry",
  "cf-ew-via",
  "cdn-loop",
  "x-forwarded-for",
  "x-real-ip",
]);

const SKIP_RES = new Set([
  "connection",
  "transfer-encoding",
  "keep-alive",
  // fetch() уже разжал тело — иначе клиент получит битый ответ
  "content-encoding",
  "content-length",
]);

function originBase(env) {
  const raw = (env && env.AMVERA_ORIGIN) || DEFAULT_ORIGIN;
  return String(raw).replace(/\/$/, "");
}

function copyRequestHeaders(request, incomingHost) {
  const headers = new Headers();
  for (const [key, value] of request.headers) {
    if (SKIP_REQ.has(key.toLowerCase())) continue;
    headers.set(key, value);
  }
  headers.set("X-Forwarded-Host", incomingHost);
  headers.set("X-Forwarded-Proto", "https");
  headers.set("X-Tsulo-Edge", "cloudflare-pages");
  return headers;
}

function copyResponseHeaders(upstream) {
  const headers = new Headers();
  for (const [key, value] of upstream.headers) {
    if (SKIP_RES.has(key.toLowerCase())) continue;
    headers.append(key, value);
  }
  headers.set("X-Tsulo-Edge", "1");
  // Не кэшировать подписки/кабинет на edge жёстко — уважаем Cache-Control origin
  return headers;
}

export async function onRequest(context) {
  const { request, env, next } = context;
  const incoming = new URL(request.url);

  // Telegram webhook обрабатывает functions/telegram/webhook.js (channel gate).
  if (
    incoming.pathname === "/telegram/webhook" ||
    incoming.pathname === "/telegram/webhook/"
  ) {
    return next();
  }

  // Служебная проверка самого edge (без Amvera)
  if (incoming.pathname === "/_edge" || incoming.pathname === "/_edge/") {
    return Response.json({
      ok: true,
      edge: "cloudflare-pages",
      origin: originBase(env),
      host: incoming.host,
    });
  }

  const target = originBase(env) + incoming.pathname + incoming.search;
  const init = {
    method: request.method,
    headers: copyRequestHeaders(request, incoming.host),
    redirect: "manual",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = request.body;
    init.duplex = "half";
  }

  try {
    const upstream = await fetch(target, init);
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: copyResponseHeaders(upstream),
    });
  } catch (err) {
    return Response.json(
      { ok: false, error: String(err), target },
      { status: 502, headers: { "X-Tsulo-Edge": "1" } },
    );
  }
}
