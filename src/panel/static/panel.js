(() => {
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => [...document.querySelectorAll(sel)];

  const state = {
    view: "dashboard",
    usersPage: 1,
    selectedId: null,
    selected: null,
  };

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
      ...opts,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.detail || data.error || res.statusText);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  function showLogin(msg = "") {
    $("#app").classList.add("hidden");
    $("#login-view").classList.remove("hidden");
    $("#login-error").textContent = msg;
  }

  function showApp() {
    $("#login-view").classList.add("hidden");
    $("#app").classList.remove("hidden");
  }

  function fmtTs(value) {
    if (!value) return "—";
    if (typeof value === "number") {
      const d = new Date(value * 1000);
      return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("ru-RU");
    }
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? value : d.toLocaleString("ru-RU");
  }

  function setView(name) {
    state.view = name;
    $$(".nav").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
    $$(".view").forEach((v) => v.classList.add("hidden"));
    const el = $(`#view-${name}`);
    if (el) el.classList.remove("hidden");
    const titles = {
      dashboard: "Dashboard",
      users: "Users",
      orders: "Payments",
      nodes: "Nodes / Pool",
      settings: "Settings",
    };
    $("#page-title").textContent = titles[name] || name;
    refresh();
  }

  async function loadDashboard() {
    const d = await api("/panel/api/dashboard");
    const badge = $("#badge-payments");
    badge.textContent = d.payments_active ? "payments ON" : "payments OFF";
    badge.className = `badge ${d.payments_active ? "on" : "off"}`;

    $("#dash-cards").innerHTML = [
      ["Users", d.users_total, `${d.users_active} active · ${d.users_expired} expired`],
      ["Online 24h", d.online_24h, `${d.users_disabled} disabled`],
      ["Revenue", `${d.revenue_rub} ₽`, `${d.orders_paid}/${d.orders_total} paid`],
      ["Configs", d.pool.configs, `pool ${d.pool.status} · real ${d.pool.source_real}`],
    ]
      .map(
        ([label, value, sub]) =>
          `<div class="stat"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`
      )
      .join("");

    const p = d.pool;
    $("#dash-pool").innerHTML = `
      status: <b>${p.status}</b><br>
      wifi: ${p.wifi} · lte: ${p.lte}<br>
      last refresh: ${fmtTs(p.last_refresh_at)}<br>
      ${p.last_error ? `error: ${p.last_error}` : "error: —"}
    `;
    $("#dash-plans").innerHTML = (d.plans || [])
      .map((x) => `<div><b>${x.title}</b> — ${x.price_rub} ₽ / ${x.months} мес. <code>${x.id}</code></div>`)
      .join("") || "нет тарифов";

    $("#settings-box").innerHTML = `
      <div><span>Bot</span><span>${d.bot_name}</span></div>
      <div><span>Public URL</span><span>${d.public_url}</span></div>
      <div><span>Payments</span><span>${d.payments_active ? "ON" : "OFF"}</span></div>
      <div><span>Platega</span><span>${d.platega ? "connected" : "—"}</span></div>
      <div><span>Panel</span><span>${location.origin}/panel</span></div>
    `;
  }

  async function loadUsers() {
    const q = $("#users-q").value.trim();
    const status = $("#users-status").value;
    const data = await api(
      `/panel/api/users?page=${state.usersPage}&limit=40&q=${encodeURIComponent(q)}&status=${encodeURIComponent(status)}`
    );
    $("#users-page").textContent = `${data.page} / ${data.pages} · ${data.total}`;
    $("#users-body").innerHTML = data.items
      .map((u) => {
        const name = u.username ? `@${u.username}` : u.full_name || u.telegram_id;
        return `<tr>
          <td>
            <div><b>${escapeHtml(name)}</b></div>
            <div class="muted">${u.telegram_id}</div>
          </td>
          <td><span class="pill ${u.status}">${u.status}</span></td>
          <td>${u.expires_at ? fmtTs(u.expires_at) : "∞ / free"}</td>
          <td>${u.sub_fetch_count}</td>
          <td>${fmtTs(u.last_seen_at)}</td>
          <td><button class="ghost" data-open="${u.telegram_id}">Open</button></td>
        </tr>`;
      })
      .join("");
  }

  async function loadOrders() {
    const data = await api("/panel/api/orders?limit=150");
    $("#orders-body").innerHTML = (data.items || [])
      .map(
        (o) => `<tr>
          <td><code>${escapeHtml(o.order_id)}</code></td>
          <td>${o.telegram_id}</td>
          <td>${escapeHtml(o.plan_id)}</td>
          <td>${o.amount} ₽</td>
          <td><span class="pill ${o.status === "paid" ? "active" : "expired"}">${o.status}</span></td>
          <td>${fmtTs(o.created_at)}</td>
        </tr>`
      )
      .join("") || `<tr><td colspan="6" class="muted">Пока нет платежей (появятся после новых оплат)</td></tr>`;
  }

  async function loadNodes() {
    const p = await api("/panel/api/pool");
    $("#nodes-detail").innerHTML = `
      <div class="kv">
        <div><span>Status</span><span>${p.status}</span></div>
        <div><span>Visible configs</span><span>${p.configs} / limit ${p.limit}</span></div>
        <div><span>Source real</span><span>${p.source_real}</span></div>
        <div><span>Wi‑Fi</span><span>${p.wifi}</span></div>
        <div><span>LTE</span><span>${p.lte}</span></div>
        <div><span>Refreshing</span><span>${p.is_refreshing ? "yes" : "no"}</span></div>
        <div><span>Last refresh</span><span>${fmtTs(p.last_refresh_at)} (${Math.round(p.last_refresh_duration || 0)}s)</span></div>
        <div><span>Fetch HTTP</span><span>${p.last_fetch_status ?? "—"}</span></div>
        <div><span>Failures</span><span>${p.consecutive_fetch_failures}</span></div>
        <div><span>Sources</span><span>${escapeHtml(JSON.stringify(p.sources || {}))}</span></div>
        <div><span>Wi‑Fi sources</span><span>${escapeHtml(JSON.stringify(p.wifi_sources || {}))}</span></div>
        <div><span>LTE sources</span><span>${escapeHtml(JSON.stringify(p.lte_sources || {}))}</span></div>
        <div><span>Last error</span><span>${escapeHtml(p.last_error || "—")}</span></div>
      </div>
      <p class="muted" style="margin-top:12px">Это imitation panel: ноды = ваш pool из upstream-источников. Реальный GB-трафик Xray появится только на своей Marzban/Remnawave ноде.</p>
    `;
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  async function openUser(id) {
    const u = await api(`/panel/api/users/${id}`);
    state.selectedId = id;
    state.selected = u;
    $("#modal-title").textContent = u.username ? `@${u.username}` : u.full_name || `User ${u.telegram_id}`;
    $("#modal-note").value = u.note || "";
    $("#modal-body").innerHTML = `
      <div class="row"><b>Telegram ID</b><span>${u.telegram_id}</span></div>
      <div class="row"><b>Status</b><span class="pill ${u.status}">${u.status}</span></div>
      <div class="row"><b>Plan</b><span>${escapeHtml(u.plan_title || u.plan || "—")}</span></div>
      <div class="row"><b>Expire</b><span>${u.expires_at ? fmtTs(u.expires_at) : "∞"}</span></div>
      <div class="row"><b>Days left</b><span>${u.time_left || (u.days_left ?? "—")}</span></div>
      <div class="row"><b>Data</b><span>${u.data_limit} · used ${u.used_traffic}</span></div>
      <div class="row"><b>Fetches</b><span>${u.sub_fetch_count} · last ${fmtTs(u.last_seen_at)}</span></div>
      <div class="row"><b>Registered</b><span>${fmtTs(u.registration_date)}</span></div>
      <div class="row"><b>HWID</b><code>${escapeHtml(u.bound_hwid || "— не привязан")}</code></div>
      <div class="row"><b>Token</b><code>${escapeHtml(u.subscription_token)}</code></div>
      <div class="row"><b>Key URL</b><code id="modal-url">${escapeHtml(u.subscription_url)}</code></div>
    `;
    $("#user-modal").showModal();
  }

  async function act(name) {
    const id = state.selectedId;
    if (!id) return;
    if (name === "copy") {
      const url = state.selected?.subscription_url || "";
      await navigator.clipboard.writeText(url);
      return;
    }
    if (name === "extend5m") await api(`/panel/api/users/${id}/extend`, { method: "POST", body: JSON.stringify({ minutes: 5 }) });
    if (name === "extend7") await api(`/panel/api/users/${id}/extend`, { method: "POST", body: JSON.stringify({ days: 7 }) });
    if (name === "extend30") await api(`/panel/api/users/${id}/extend`, { method: "POST", body: JSON.stringify({ days: 30 }) });
    if (name === "extend180") await api(`/panel/api/users/${id}/extend`, { method: "POST", body: JSON.stringify({ days: 182 }) });
    if (name === "extend365") await api(`/panel/api/users/${id}/extend`, { method: "POST", body: JSON.stringify({ days: 365 }) });
    if (name === "expire") await api(`/panel/api/users/${id}/expire`, { method: "POST", body: JSON.stringify({}) });
    if (name === "disable") await api(`/panel/api/users/${id}/disable`, { method: "POST", body: JSON.stringify({ disabled: true }) });
    if (name === "enable") await api(`/panel/api/users/${id}/disable`, { method: "POST", body: JSON.stringify({ disabled: false }) });
    if (name === "regen") {
      if (!confirm("Сгенерировать новый ключ? Старый URL в Happ перестанет работать.")) return;
      await api(`/panel/api/users/${id}/regen`, { method: "POST", body: "{}" });
    }
    if (name === "reset-hwid") {
      if (!confirm("Сбросить привязку устройства? Ключ можно будет добавить на новый телефон.")) return;
      await api(`/panel/api/users/${id}/reset-hwid`, { method: "POST", body: "{}" });
    }
    if (name === "note") {
      await api(`/panel/api/users/${id}/note`, {
        method: "POST",
        body: JSON.stringify({ note: $("#modal-note").value }),
      });
    }
    await openUser(id);
    if (state.view === "users") await loadUsers();
    if (state.view === "dashboard") await loadDashboard();
  }

  async function refresh() {
    const title = $("#page-title");
    const prev = title.textContent;
    title.textContent = prev + " · загрузка…";
    try {
      if (state.view === "dashboard" || state.view === "settings") await loadDashboard();
      if (state.view === "users") await loadUsers();
      if (state.view === "orders") await loadOrders();
      if (state.view === "nodes") await loadNodes();
    } catch (err) {
      console.error(err);
      if (err.status === 401 || err.status === 503) showLogin(err.message || "Нужен вход");
      else {
        const msg = err.message || String(err);
        $("#dash-cards").innerHTML = `<div class="stat"><div class="label">Ошибка</div><div class="value">!</div><div class="sub">${msg}</div></div>`;
        alert(msg);
      }
    } finally {
      const titles = {
        dashboard: "Dashboard",
        users: "Users",
        orders: "Payments",
        nodes: "Nodes / Pool",
        settings: "Settings",
      };
      title.textContent = titles[state.view] || state.view;
    }
  }

  async function boot() {
    try {
      const st = await api("/panel/api/status");
      if (!st.enabled) {
        showLogin("ADMIN_PANEL_TOKEN не задан в Amvera");
        return;
      }
      try {
        await api("/panel/api/stats/users-count");
      } catch (err) {
        if (err.status === 401 || err.status === 503) {
          showLogin(err.message || "");
          return;
        }
      }
      showApp();
      setView("dashboard");
    } catch (err) {
      showLogin(err.status === 401 ? "" : err.message || "");
    }
  }

  $("#login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/panel/api/login", {
        method: "POST",
        body: JSON.stringify({ token: $("#login-token").value }),
      });
      showApp();
      setView("dashboard");
    } catch (err) {
      $("#login-error").textContent = err.message || "Ошибка входа";
    }
  });

  $("#btn-logout").addEventListener("click", async () => {
    await api("/panel/api/logout", { method: "POST", body: "{}" });
    showLogin();
  });
  $("#btn-refresh").addEventListener("click", refresh);
  $$(".nav").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));
  $("#users-prev").addEventListener("click", () => {
    state.usersPage = Math.max(1, state.usersPage - 1);
    loadUsers().catch((e) => alert(e.message));
  });
  $("#users-next").addEventListener("click", () => {
    state.usersPage += 1;
    loadUsers().catch((e) => alert(e.message));
  });
  let t = null;
  $("#users-q").addEventListener("input", () => {
    clearTimeout(t);
    t = setTimeout(() => {
      state.usersPage = 1;
      loadUsers().catch((e) => alert(e.message));
    }, 250);
  });
  $("#users-status").addEventListener("change", () => {
    state.usersPage = 1;
    loadUsers().catch((e) => alert(e.message));
  });
  $("#users-body").addEventListener("click", (e) => {
    const id = e.target?.dataset?.open;
    if (id) openUser(id).catch((err) => alert(err.message));
  });
  $("#modal-close").addEventListener("click", () => $("#user-modal").close());
  $$("#user-form [data-act]").forEach((b) =>
    b.addEventListener("click", () => act(b.dataset.act).catch((err) => alert(err.message)))
  );
  $("#btn-pool-refresh").addEventListener("click", async () => {
    try {
      await api("/panel/api/pool/refresh", { method: "POST", body: "{}" });
      await loadNodes();
    } catch (err) {
      alert(err.message);
    }
  });

  boot();
})();
