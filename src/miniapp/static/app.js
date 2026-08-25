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
  const cardBtn = document.getElementById("btn-card");
  const cardHint = document.getElementById("card-hint");
  const statusValue = document.getElementById("status-value");
  const payBank = document.getElementById("pay-bank");
  const payName = document.getElementById("pay-name");
  const linkSupport = document.getElementById("link-support");
  const linkIg = document.getElementById("link-ig");

  let accessUrl = "";
  let cardDigits = "2202209226540747";

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

  function spaced(digits) {
    return (digits.match(/.{1,4}/g) || [digits]).join(" ");
  }

  async function loadMeta() {
    try {
      const res = await fetch("/miniapp/api/meta");
      const data = await res.json();
      if (data.card) {
        cardDigits = data.card;
        cardBtn.textContent = data.card_spaced || spaced(data.card);
      }
      if (data.card_name) payName.textContent = data.card_name;
      if (data.bank) payBank.textContent = data.bank;
      if (data.support) linkSupport.href = data.support;
      if (data.instagram) linkIg.href = data.instagram;
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
        statusValue.textContent = "нужен /start";
        return;
      }
      accessUrl = data.url || "";
      statusValue.textContent = "активен";
      if (data.card) {
        cardDigits = data.card;
        cardBtn.textContent = spaced(data.card);
      }
      if (data.card_name) payName.textContent = data.card_name;
      if (data.bank) payBank.textContent = data.bank;
      if (data.support) linkSupport.href = data.support;
      if (data.instagram) linkIg.href = data.instagram;
    } catch (_) {
      hint(copyHint, "Не удалось загрузить ссылку, попробуйте ещё раз");
    }
  }

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

  cardBtn.addEventListener("click", async () => {
    const ok = await copyText(cardDigits);
    hint(cardHint, ok ? "Номер карты скопирован" : "Скопируйте номер вручную");
  });

  loadMeta();
  loadAccess();
})();
