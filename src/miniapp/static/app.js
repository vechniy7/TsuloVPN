(function () {
  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  let TARGET = 7;
  let PROBE_TIMEOUT = 5000;
  const CONCURRENCY = 8;

  const $ = (id) => document.getElementById(id);

  const stepWifi = $("step-wifi");
  const stepProbe = $("step-probe");
  const stepDone = $("step-done");
  const stepError = $("step-error");

  function showStep(step) {
    [stepWifi, stepProbe, stepDone, stepError].forEach((el) => el.classList.add("hidden"));
    step.classList.remove("hidden");
  }

  function getInitData() {
    return tg?.initData || "";
  }

  async function apiGet(path) {
    const res = await fetch(path, {
      headers: { "X-Telegram-Init-Data": getInitData() },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  }

  async function apiPost(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": getInitData(),
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  }

  function probeWebSocket(target, timeoutMs) {
    return new Promise((resolve) => {
      const start = performance.now();
      const tls = target.security === "tls" || target.port === 443 || target.port === 8443;
      const scheme = tls ? "wss" : "ws";
      let path = target.path || "/";
      if (!path.startsWith("/")) path = "/" + path;

      let settled = false;
      const finish = (ok, ms) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        try { ws.close(); } catch (_) {}
        resolve({ ok, ms: ms ?? Math.round(performance.now() - start) });
      };

      let ws;
      try {
        ws = new WebSocket(`${scheme}://${target.host}:${target.port}${path}`);
      } catch (_) {
        finish(false);
        return;
      }

      const timer = setTimeout(() => finish(false), timeoutMs);

      ws.onopen = () => finish(true);
      ws.onerror = () => {
        const ms = Math.round(performance.now() - start);
        finish(ms > 80 && ms < timeoutMs - 100, ms);
      };
    });
  }

  async function probeHttps(target, timeoutMs) {
    const start = performance.now();
    const port = target.port;
    const scheme = port === 80 ? "http" : "https";
    let path = target.path || "/";
    if (!path.startsWith("/")) path = "/" + path;
    const url = `${scheme}://${target.host}:${port}${path}`;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    try {
      await fetch(url, {
        mode: "no-cors",
        signal: controller.signal,
        cache: "no-store",
      });
    } catch (_) {
      // ожидаемо — измеряем время до ответа/ошибки
    } finally {
      clearTimeout(timer);
    }

    const ms = Math.round(performance.now() - start);
    const alive = ms >= 50 && ms < timeoutMs - 50;
    return { ok: alive, ms };
  }

  async function probeTarget(target, timeoutMs) {
    if (target.transport === "ws") {
      return probeWebSocket(target, timeoutMs);
    }
    return probeHttps(target, timeoutMs);
  }

  async function runPool(tasks, limit, worker) {
    const results = [];
    let index = 0;
    let stop = false;

    async function runner() {
      while (!stop && index < tasks.length) {
        const i = index++;
        const result = await worker(tasks[i], i);
        results[i] = result;
        if (result?.stopPool) stop = true;
      }
    }

    const runners = Array.from({ length: Math.min(limit, tasks.length) }, () => runner());
    await Promise.all(runners);
    return { results, stopped: stop };
  }

  function updateProgress(checked, total, found, target) {
    $("stat-found").textContent = found;
    $("stat-target").textContent = target;
    $("stat-checked").textContent = checked;
    $("stat-total").textContent = total;
    const pct = total ? Math.min(100, Math.round((checked / total) * 100)) : 0;
    $("progress-bar").style.width = pct + "%";
  }

  function addFoundItem(target, ms) {
    const li = document.createElement("li");
    const flag = target.sni ? target.sni.split(".")[0] : target.host;
    li.textContent = `✓ ${flag} — ${ms} мс`;
    $("found-list").appendChild(li);
  }

  async function startProbe() {
    showStep(stepProbe);
    $("found-list").innerHTML = "";
    $("probe-status").textContent = "Загрузка списка обходов...";

    let data;
    try {
      data = await apiGet("/miniapp/api/configs");
    } catch (e) {
      $("error-text").textContent = e.message || "Не удалось загрузить конфиги";
      showStep(stepError);
      return;
    }

    const targets = data.targets || [];
    TARGET = data.target || TARGET;
    PROBE_TIMEOUT = data.timeout_ms || PROBE_TIMEOUT;
    const targetCount = TARGET;
    $("stat-target").textContent = targetCount;

    if (!targets.length) {
      $("error-text").textContent = "Список обходов пуст. Попробуйте позже.";
      showStep(stepError);
      return;
    }

    const working = [];
    let checked = 0;
    const total = targets.length;
    updateProgress(0, total, 0, targetCount);

    let stoppedEarly = false;

    await runPool(targets, CONCURRENCY, async (target) => {
      if (working.length >= targetCount || stoppedEarly) {
        return { stopPool: true };
      }

      $("probe-status").textContent = `Проверка ${target.host}:${target.port}...`;

      const { ok, ms } = await probeTarget(target, PROBE_TIMEOUT);
      checked++;
      updateProgress(checked, total, working.length, targetCount);

      if (ok && working.length < targetCount) {
        working.push({ id: target.id, uri: target.uri, ms });
        addFoundItem(target, ms);
        updateProgress(checked, total, working.length, targetCount);

        if (working.length >= targetCount) {
          stoppedEarly = true;
          return { stopPool: true };
        }
      }

      if (checked >= total) {
        return { stopPool: true };
      }
      return {};
    });

    $("probe-status").textContent = "Сохранение результата...";

    if (!working.length) {
      $("error-text").textContent =
        "Не найдено рабочих обходов с вашего устройства. Попробуйте снова на мобильном интернете.";
      showStep(stepError);
      return;
    }

    try {
      const saveResult = await apiPost("/miniapp/api/save", {
        configs: working.map((w) => ({ id: w.id, uri: w.uri, ms: w.ms })),
      });

      const count = saveResult.count || working.length;
      $("done-text").textContent =
        `Найдено ${count} рабочих обходов. Персональный ключ для Happ создан.`;

      if (tg) {
        tg.sendData(JSON.stringify({ ok: true, count }));
      }
      showStep(stepDone);
    } catch (e) {
      $("error-text").textContent = e.message || "Ошибка сохранения";
      showStep(stepError);
    }
  }

  $("btn-wifi-off").addEventListener("click", startProbe);
  $("btn-close").addEventListener("click", () => tg?.close());
  $("btn-retry").addEventListener("click", () => showStep(stepWifi));
})();
