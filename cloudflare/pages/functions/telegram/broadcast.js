/**
 * Запуск рассылки с Amvera/панели.
 * Amvera не ходит в api.telegram.org — edge шлёт сообщения сам.
 *
 * Auth: Authorization: Bearer <ADMIN_PANEL_TOKEN>
 * Env: BOT_TOKEN, ADMIN_PANEL_TOKEN
 */
import { runBroadcast } from "../_lib/tg_broadcast.js";

function authorized(request, env) {
  const expected = String((env && env.ADMIN_PANEL_TOKEN) || "").trim();
  if (!expected) return false;
  const auth = request.headers.get("Authorization") || "";
  const bearer = auth.toLowerCase().startsWith("bearer ")
    ? auth.slice(7).trim()
    : "";
  const hdr = (request.headers.get("X-Admin-Token") || "").trim();
  return bearer === expected || hdr === expected;
}

export async function onRequest(context) {
  const { request, env } = context;

  if (request.method === "GET") {
    return Response.json({
      ok: true,
      relay: "telegram-broadcast",
      has_token: Boolean(env.BOT_TOKEN),
      has_panel_token: Boolean(env.ADMIN_PANEL_TOKEN),
    });
  }

  if (request.method !== "POST") {
    return new Response("method not allowed", { status: 405 });
  }

  if (!authorized(request, env)) {
    return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
  }

  const token = String((env && env.BOT_TOKEN) || "").trim();
  if (!token) {
    return Response.json({ ok: false, error: "BOT_TOKEN missing" }, { status: 503 });
  }

  let job;
  try {
    job = await request.json();
  } catch (_) {
    return Response.json({ ok: false, error: "invalid json" }, { status: 400 });
  }

  if (!job || typeof job !== "object" || !Array.isArray(job.recipients)) {
    return Response.json({ ok: false, error: "recipients required" }, { status: 400 });
  }

  const total = job.recipients.length;
  if (context && typeof context.waitUntil === "function") {
    context.waitUntil(
      runBroadcast(token, job).catch((err) =>
        console.log("broadcast failed", String(err)),
      ),
    );
  } else {
    await runBroadcast(token, job);
  }

  return Response.json({
    ok: true,
    via: "cf-broadcast",
    broadcast_total: total,
    accepted: true,
  });
}
