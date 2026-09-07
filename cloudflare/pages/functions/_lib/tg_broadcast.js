/** Общая отправка рассылки через Bot API (Cloudflare edge). */

export async function sleep(ms) {
  await new Promise((r) => setTimeout(r, ms));
}

export async function tgApi(token, method, body) {
  if (method === "editMessageMedia" && body && body.media && typeof body.media === "object") {
    if (!body.media.type) body.media.type = "photo";
  }
  const res = await fetch(`https://api.telegram.org/bot${token}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!data || data.ok === false) {
    console.log(
      "tgApi fail",
      method,
      data && data.description ? data.description : res.status,
    );
  }
  return data;
}

export async function runBroadcast(token, job) {
  const recipients = Array.isArray(job && job.recipients) ? job.recipients : [];
  const parseMode = (job && job.parse_mode) || "HTML";
  const photo = (job && job.photo_file_id) || "";
  const text = (job && (job.text || job.caption)) || "";
  let sent = 0;
  let blocked = 0;
  let failed = 0;

  for (const chatId of recipients) {
    try {
      let data;
      if (photo) {
        data = await tgApi(token, "sendPhoto", {
          chat_id: chatId,
          photo,
          caption: text || undefined,
          parse_mode: text ? parseMode : undefined,
        });
      } else {
        data = await tgApi(token, "sendMessage", {
          chat_id: chatId,
          text: text || " ",
          parse_mode: parseMode,
          disable_web_page_preview: true,
        });
      }
      if (data && data.ok === false) {
        const desc = String((data && data.description) || "").toLowerCase();
        if (
          desc.includes("blocked") ||
          desc.includes("deactivated") ||
          desc.includes("chat not found")
        ) {
          blocked += 1;
        } else {
          failed += 1;
        }
      } else {
        sent += 1;
      }
    } catch (_) {
      failed += 1;
    }
    await sleep(40);
  }

  const adminId = job && job.admin_id;
  if (adminId) {
    try {
      await tgApi(token, "sendMessage", {
        chat_id: adminId,
        text:
          `<b>Рассылка завершена</b>\n\n` +
          `Доставлено: <b>${sent}</b>\n` +
          `Заблокировали бота: <b>${blocked}</b>\n` +
          `Ошибки: <b>${failed}</b>\n` +
          `Всего: <b>${recipients.length}</b>`,
        parse_mode: "HTML",
      });
    } catch (err) {
      console.log("broadcast admin notify failed", String(err));
    }
  }
  return { sent, blocked, failed, total: recipients.length };
}
