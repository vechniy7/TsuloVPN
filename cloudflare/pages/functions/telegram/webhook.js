/**
 * Cloudflare Pages Function — Telegram ↔ Amvera relay.
 * URL: https://<project>.pages.dev/telegram/webhook
 */
const AMVERA =
  "https://tsulovpn-culoebali.amvera.io/telegram/webhook";

export async function onRequest(context) {
  const { request } = context;
  const url = new URL(request.url);

  if (!url.pathname.endsWith("/telegram/webhook") && url.pathname !== "/") {
    return new Response("not found", { status: 404 });
  }

  if (request.method === "GET") {
    return Response.json({ ok: true, relay: AMVERA, via: "pages" });
  }

  if (request.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }

  const body = await request.arrayBuffer();
  try {
    const upstream = await fetch(AMVERA, {
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
    return Response.json({ ok: false, error: String(err) }, { status: 502 });
  }
}
