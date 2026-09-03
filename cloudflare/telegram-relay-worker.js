/**
 * Cloudflare Worker: Telegram → Amvera webhook relay.
 *
 * Telegram стабильно достучится до workers.dev, а Worker — до Amvera.
 * Ответ Amvera (sendMessage JSON) возвращаем Telegram как есть.
 *
 * Deploy:
 *   npx wrangler login
 *   npx wrangler deploy
 * Затем:
 *   setWebhook на https://<worker>.workers.dev/telegram/webhook
 */
export default {
  async fetch(request, env) {
    const amvera =
      env.AMVERA_WEBHOOK_URL ||
      "https://tsulovpn-culoebali.amvera.io/telegram/webhook";
    const url = new URL(request.url);

    if (url.pathname !== "/telegram/webhook" && url.pathname !== "/") {
      return new Response("not found", { status: 404 });
    }

    if (request.method === "GET") {
      return Response.json({ ok: true, relay: amvera });
    }

    if (request.method !== "POST") {
      return new Response("method not allowed", { status: 405 });
    }

    const body = await request.arrayBuffer();
    try {
      const upstream = await fetch(amvera, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body,
      });
      const text = await upstream.text();
      return new Response(text, {
        status: upstream.status,
        headers: {
          "content-type":
            upstream.headers.get("content-type") || "application/json",
        },
      });
    } catch (err) {
      return Response.json(
        { ok: false, error: String(err) },
        { status: 502 }
      );
    }
  },
};
