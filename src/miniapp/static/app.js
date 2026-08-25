(() => {
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    try {
      tg.setHeaderColor("#f4f2ed");
      tg.setBackgroundColor("#f4f2ed");
    } catch (_) {
      /* older clients */
    }
  }

  const copyBtn = document.getElementById("btn-copy");
  const copyHint = document.getElementById("copy-hint");
  const statusValue = document.getElementById("status-value");
  const linkSupport = document.getElementById("link-support");

  let accessUrl = "";

  function hint(el, text) {
    if (el) el.textContent = text;
  }

  async function copyText(value) {
    if (!value) return false;
    try {
      await navigator.clipboard.writeText(value);
      if (tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
      return true;
    } catch (_) {
      const area = document.createElement("textarea");
      area.value = value;
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      area.remove();
      return ok;
    }
  }

  async function loadMeta() {
    try {
      const res = await fetch("/miniapp/api/meta");
      const data = await res.json();
      if (data.support && linkSupport) linkSupport.href = data.support;
    } catch (_) {
      /* keep defaults */
    }
  }

  async function loadAccess() {
    const initData = (tg && tg.initData) || "";
    if (!initData) {
      hint(copyHint, "Откройте кабинет из Telegram-бота");
      return;
    }
    try {
      const res = await fetch("/miniapp/api/access", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData }),
      });
      const data = await res.json();
      if (!data.ok) {
        hint(copyHint, "Нажмите /start в боте, затем откройте кабинет снова");
        if (statusValue) statusValue.textContent = "нужен /start";
        return;
      }
      accessUrl = data.url || "";
      if (statusValue) statusValue.textContent = "активен";
      if (data.support && linkSupport) linkSupport.href = data.support;
    } catch (_) {
      hint(copyHint, "Не удалось загрузить ссылку, попробуйте ещё раз");
    }
  }

  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      if (!accessUrl) {
        await loadAccess();
      }
      if (!accessUrl) {
        hint(copyHint, "Ссылку можно взять в боте — «Мой доступ»");
        return;
      }
      const ok = await copyText(accessUrl);
      hint(copyHint, ok ? "Ссылка скопирована" : "Скопируйте ссылку в боте");
    });
  }

  loadMeta();
  loadAccess();
})();
