const state = {
  user: null,
  view: "tmdb",
  settings: {},
  subscriptions: [],
  resources: [],
  mediaPayloads: new Map(),
  tmdbSearch: [],
  logsMode: "simple",
  settingsTab: "credentials",
};

const navItems = [
  ["tmdb", "TMDB 榜单", "热门剧集和电影，点一下就能订阅"],
  ["emby", "Emby 看板", "媒体数量、媒体库、用户与观看历史"],
  ["subscriptions", "我的订阅", "管理剧集和电影追新规则"],
  ["logs", "日志", "查看运行状态和调试信息"],
  ["settings", "设置", "账号、115、Telegram、TMDB、代理和媒体库"],
];

const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    let message = res.statusText;
    try { message = (await res.json()).detail || message; } catch {}
    throw new Error(message);
  }
  return res.status === 204 ? null : res.json();
}

function toast(message) {
  const old = $(".toast");
  if (old) old.remove();
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2800);
}

function posterUrl(item) {
  return item.poster_path ? `https://image.tmdb.org/t/p/w500${item.poster_path}` : "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=600&q=80";
}

function backdropUrl(item) {
  return item.backdrop_path ? `https://image.tmdb.org/t/p/w1280${item.backdrop_path}` : posterUrl(item);
}

async function boot() {
  try {
    state.user = await api("/api/auth/me");
    await refreshBase();
    renderApp();
  } catch {
    renderLogin();
  }
}

async function refreshBase() {
  state.settings = await api("/api/settings");
  state.subscriptions = await api("/api/subscriptions");
  state.resources = await api("/api/resources");
}

function renderLogin() {
  $("#app").innerHTML = `
    <main class="login">
      <section class="login-card">
        <h1>ToGo115</h1>
        <p>115 网盘资源订阅与追新控制台</p>
        <form id="loginForm">
          <label>账号 <input name="username" autocomplete="username" value="admin" /></label>
          <label>密码 <input name="password" type="password" autocomplete="current-password" value="admin123" /></label>
          <button type="submit">登录</button>
        </form>
      </section>
    </main>
  `;
  $("#loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api("/api/auth/login", { method: "POST", body: JSON.stringify(Object.fromEntries(form)) });
      state.user = await api("/api/auth/me");
      await refreshBase();
      renderApp();
    } catch (error) {
      toast(error.message);
    }
  });
}

function renderApp() {
  const current = navItems.find(([key]) => key === state.view);
  $("#app").innerHTML = `
    <div class="shell">
      <aside class="sidebar">
        <div class="brand"><div class="brand-mark">115</div><div><strong>ToGo115</strong><span>资源订阅系统</span></div></div>
        <nav class="nav">
          ${navItems.map(([key, label]) => `<button class="${state.view === key ? "active" : ""}" data-view="${key}">${label}</button>`).join("")}
        </nav>
      </aside>
      <main class="main">
        <header class="topbar">
          <div><h2>${current[1]}</h2><p>${current[2]}</p></div>
          <button class="secondary" id="logoutBtn">退出</button>
        </header>
        <div id="view"></div>
      </main>
    </div>
  `;
  document.querySelectorAll("[data-view]").forEach((btn) => btn.addEventListener("click", () => {
    state.view = btn.dataset.view;
    renderApp();
  }));
  $("#logoutBtn").addEventListener("click", async () => {
    await api("/api/auth/logout", { method: "POST" });
    renderLogin();
  });
  renderView();
}

function renderView() {
  if (state.view === "tmdb") renderTmdb();
  if (state.view === "emby") renderEmby();
  if (state.view === "subscriptions") renderSubscriptions();
  if (state.view === "logs") renderLogs();
  if (state.view === "settings") renderSettings();
}

async function renderTmdb() {
  const root = $("#view");
  root.innerHTML = `
    <section class="toolbar">
      <label>搜索 TMDB <input id="tmdbQuery" placeholder="输入剧集或电影名称" /></label>
      <button id="tmdbSearchBtn">搜索</button>
    </section>
    <section class="section" id="searchSection"></section>
    <section class="section" id="trendingSection"><div class="empty">正在读取 TMDB 榜单...</div></section>
  `;
  $("#tmdbSearchBtn").addEventListener("click", () => searchTmdb());
  $("#tmdbQuery").addEventListener("keydown", (event) => {
    if (event.key === "Enter") searchTmdb();
  });
  try {
    const data = await api("/api/tmdb/trending");
    const tv = data.tv || [];
    const movie = data.movie || [];
    $("#trendingSection").innerHTML = `
      <h3>热门剧集</h3>
      ${mediaGrid(tv, "tv")}
      <h3>热门电影</h3>
      ${mediaGrid(movie, "movie")}
    `;
    bindMediaActions(root);
  } catch (error) {
    $("#trendingSection").innerHTML = `<div class="empty">TMDB 未配置或暂时不可用。配置 API Key 后可搜索和订阅。</div>`;
  }
}

function mediaGrid(items, type) {
  if (!items.length) return `<div class="empty">暂无数据，配置 TMDB API Key 后会显示榜单。</div>`;
  const visibleItems = items.slice(0, 14);
  return `<div class="media-grid">${visibleItems.map((item) => {
    const title = item.name || item.title;
    const mediaType = item.media_type === "movie" || item.media_type === "tv" ? item.media_type : type;
    const payloadId = `${mediaType}-${item.id}`;
    const payload = {
      title,
      media_type: mediaType,
      tmdb_id: item.id,
      poster_url: posterUrl(item),
      overview: item.overview || "",
      keywords: [title],
    };
    state.mediaPayloads.set(payloadId, payload);
    return `<article class="media-card">
      <button class="poster-button" data-detail="${payloadId}" aria-label="查看 ${title} 详情">
        <img class="poster" src="${posterUrl(item)}" alt="${title}" />
        <span class="poster-overlay">
          <span data-subscribe="${payloadId}">订阅</span>
          <span>详情</span>
        </span>
      </button>
      <div class="media-meta">
        <h3>${title}</h3>
        <p>${mediaType === "tv" ? "电视剧" : "电影"} · ${(item.first_air_date || item.release_date || "").slice(0, 4) || "未知"}</p>
      </div>
    </article>`;
  }).join("")}</div>`;
}

function bindMediaActions(root = document) {
  root.querySelectorAll("[data-subscribe]").forEach((btn) => btn.addEventListener("click", async (event) => {
    event.stopPropagation();
    const item = state.mediaPayloads.get(btn.dataset.subscribe);
    await subscribeMedia(item);
  }));
  root.querySelectorAll("[data-detail]").forEach((btn) => btn.addEventListener("click", () => showMediaDetail(btn.dataset.detail)));
}

async function subscribeMedia(item) {
  if (!item) return;
  await api("/api/subscriptions", { method: "POST", body: JSON.stringify(item) });
  await refreshBase();
  toast("已创建订阅并开始搜索历史消息");
}

async function searchTmdb() {
  const query = $("#tmdbQuery").value.trim();
  if (!query) return toast("请输入搜索内容");
  const section = $("#searchSection");
  section.innerHTML = `<div class="empty">正在搜索...</div>`;
  const data = await api(`/api/tmdb/search?q=${encodeURIComponent(query)}`);
  state.tmdbSearch = data.results || [];
  section.innerHTML = `<h3>搜索结果</h3>${mediaGrid(state.tmdbSearch, "tv")}`;
  bindMediaActions(section);
}

async function showMediaDetail(payloadId) {
  const payload = state.mediaPayloads.get(payloadId);
  if (!payload) return;
  let detail = {};
  try {
    detail = await api(`/api/tmdb/${payload.media_type}/${payload.tmdb_id}`);
  } catch {
    detail = payload;
  }
  const title = detail.name || detail.title || payload.title;
  const seasons = payload.media_type === "tv" && detail.number_of_episodes ? `<span>${detail.number_of_episodes} 集</span>` : "";
  const runtime = payload.media_type === "movie" && detail.runtime ? `<span>${detail.runtime} 分钟</span>` : "";
  document.body.insertAdjacentHTML("beforeend", `
    <div class="modal-backdrop" id="mediaModal">
      <section class="detail-panel">
        <button class="detail-close" id="detailClose">×</button>
        <div class="detail-hero" style="background-image: linear-gradient(90deg, rgba(16,47,49,.92), rgba(16,47,49,.52)), url('${backdropUrl(detail)}')">
          <img src="${posterUrl(detail)}" alt="${title}" />
          <div>
            <h2>${title}</h2>
            <div class="detail-facts">
              <span>${payload.media_type === "tv" ? "电视剧" : "电影"}</span>
              <span>${(detail.first_air_date || detail.release_date || "").slice(0, 4) || "未知年份"}</span>
              ${seasons}${runtime}
            </div>
            <p>${detail.overview || payload.overview || "暂无简介"}</p>
            <button id="detailSubscribe">订阅</button>
          </div>
        </div>
      </section>
    </div>
  `);
  $("#detailClose").addEventListener("click", () => $("#mediaModal").remove());
  $("#mediaModal").addEventListener("click", (event) => {
    if (event.target.id === "mediaModal") $("#mediaModal").remove();
  });
  $("#detailSubscribe").addEventListener("click", async () => {
    await subscribeMedia(payload);
    $("#mediaModal").remove();
  });
}

async function renderEmby() {
  const root = $("#view");
  root.innerHTML = `<div class="empty">正在读取 Emby 看板...</div>`;
  const data = await api("/api/emby/dashboard");
  root.innerHTML = `
    ${data.error ? `<div class="empty">Emby 数据获取失败：${data.error}</div>` : ""}
    <section class="stats">
      <div class="stat"><span>媒体总数</span><b>${data.media_count || 0}</b></div>
      <div class="stat"><span>媒体库</span><b>${(data.libraries || []).length}</b></div>
      <div class="stat"><span>用户</span><b>${(data.users || []).length}</b></div>
      <div class="stat"><span>观看记录</span><b>${(data.history || []).length}</b></div>
    </section>
    <section class="section"><h3>媒体库封面</h3>${embyGrid(data.libraries, "暂无媒体库数据", "library")}</section>
    <section class="section"><h3>用户</h3>${embyGrid(data.users, "暂无用户数据", "user")}</section>
    <section class="section"><h3>观看历史</h3>${embyGrid(data.history, "暂无观看历史", "history")}</section>
  `;
}

function simpleList(items, empty) {
  if (!items || !items.length) return `<div class="empty">${empty}</div>`;
  return `<div class="grid">${items.map((item) => `<div class="card"><div class="card-body"><h3>${item.name || item.title || "项目"}</h3><p class="muted">${item.description || ""}</p></div></div>`).join("")}</div>`;
}

function embyGrid(items, empty, kind) {
  if (!items || !items.length) return `<div class="empty">${empty}</div>`;
  return `<div class="emby-grid">${items.map((item) => {
    const image = item.image_url ? `<img src="${item.image_url}" alt="${item.name || item.title || "Emby"}" />` : `<div class="emby-placeholder">${kind === "user" ? "用户" : "媒体"}</div>`;
    return `<article class="emby-card">
      ${image}
      <div>
        <h3>${item.name || item.title || "项目"}</h3>
        <p>${item.description || item.collection_type || item.date_played || ""}</p>
      </div>
    </article>`;
  }).join("")}</div>`;
}

function renderSubscriptions() {
  $("#view").innerHTML = `
    ${subscriptionTable()}
    <section class="section">
      <h3>最近发现的资源</h3>
      ${resourceTable()}
    </section>
  `;
  document.querySelectorAll("[data-delete]").forEach((btn) => btn.addEventListener("click", async () => {
    await api(`/api/subscriptions/${btn.dataset.delete}`, { method: "DELETE" });
    await refreshBase();
    renderSubscriptions();
  }));
  document.querySelectorAll("[data-search]").forEach((btn) => btn.addEventListener("click", async () => {
    const res = await api(`/api/subscriptions/${btn.dataset.search}/search`, { method: "POST" });
    toast(`搜索完成，新增 ${res.count} 条资源`);
  }));
  document.querySelectorAll("[data-edit]").forEach((btn) => btn.addEventListener("click", async () => {
    const id = btn.dataset.edit;
    const keywords = prompt("输入新的关键词，多个用逗号分隔");
    if (keywords === null) return;
    await api(`/api/subscriptions/${id}`, { method: "PUT", body: JSON.stringify({ keywords: keywords.split(",").map((x) => x.trim()).filter(Boolean) }) });
    await refreshBase();
    renderSubscriptions();
  }));
  document.querySelectorAll("[data-deliver]").forEach((btn) => btn.addEventListener("click", async () => {
    const res = await api(`/api/resources/${btn.dataset.deliver}/deliver`, { method: "POST" });
    state.resources = await api("/api/resources");
    renderSubscriptions();
    toast(res.ok ? "已重新投递" : "投递失败，请看日志");
  }));
}

function subscriptionTable() {
  if (!state.subscriptions.length) return `<div class="empty">还没有订阅。可以从 TMDB 榜单或搜索结果里添加。</div>`;
  return `<table class="table">
    <thead><tr><th>名称</th><th>类型</th><th>入库状态</th><th>关键词</th><th>操作</th></tr></thead>
    <tbody>${state.subscriptions.map((item) => {
      const library = item.media_type === "movie"
        ? (item.in_library ? "已入库" : "未入库")
        : `${item.emby_count || 0}/${item.tmdb_total_count || 0}`;
      return `<tr>
        <td><strong>${item.title}</strong><br><span class="muted">${item.status}</span></td>
        <td><span class="pill">${item.media_type === "tv" ? "电视剧" : "电影"}</span></td>
        <td>${library}</td>
        <td>${(item.keywords || []).join(", ")}</td>
        <td><div class="row-actions"><button class="secondary" data-search="${item.id}">搜索</button><button class="secondary" data-edit="${item.id}">关键词</button><button class="danger" data-delete="${item.id}">取消订阅</button></div></td>
      </tr>`;
    }).join("")}</tbody>
  </table>`;
}

function resourceTable() {
  if (!state.resources.length) return `<div class="empty">还没有发现资源链接。</div>`;
  return `<table class="table">
    <thead><tr><th>订阅</th><th>链接</th><th>来源</th><th>状态</th><th>操作</th></tr></thead>
    <tbody>${state.resources.map((item) => `<tr>
      <td>${item.subscription_title}</td>
      <td><a href="${item.url}" target="_blank" rel="noreferrer">${item.url}</a></td>
      <td>${item.source}<br><span class="muted">${item.message_id || ""}</span></td>
      <td><span class="pill">${item.status}</span></td>
      <td><button class="secondary" data-deliver="${item.id}">重试</button></td>
    </tr>`).join("")}</tbody>
  </table>`;
}

async function renderLogs() {
  const root = $("#view");
  root.innerHTML = `
    <section class="toolbar">
      <button class="${state.logsMode === "simple" ? "" : "secondary"}" data-mode="simple">简易日志</button>
      <button class="${state.logsMode === "debug" ? "" : "secondary"}" data-mode="debug">Debug</button>
    </section>
    <div class="log-list"><div class="empty">正在读取日志...</div></div>
  `;
  root.querySelectorAll("[data-mode]").forEach((btn) => btn.addEventListener("click", () => {
    state.logsMode = btn.dataset.mode;
    renderLogs();
  }));
  const logs = await api(`/api/logs?mode=${state.logsMode}`);
  root.querySelector(".log-list").innerHTML = logs.length ? logs.map((log) => `
    <div class="log-item ${log.level}">
      <strong>${log.level.toUpperCase()} · ${log.scope}</strong>
      <div>${log.message}</div>
      <small class="muted">${new Date(log.created_at).toLocaleString()}</small>
    </div>
  `).join("") : `<div class="empty">暂无日志</div>`;
}

function renderSettings() {
  const tabs = [
    ["credentials", "账号安全"],
    ["delivery", "推送方式"],
    ["115", "115 网盘"],
    ["telegram", "Telegram"],
    ["tmdb", "TMDB"],
    ["proxy", "代理设置"],
    ["tg_bot", "TG Bot"],
    ["emby", "媒体库"],
  ];
  const cards = {
    credentials: settingsCard("账号安全", "credentials", [
      ["username", "账号", state.user.username],
      ["password", "新密码", "", "password"],
    ]),
    delivery: settingsCard("推送方式", "delivery", [["mode", "全局推送方式"]]),
    115: settingsCard("115 网盘", "115", [["cookie", "Cookie"], ["target_path", "默认转存目录"], ["qr_login", "扫码登录状态"]]),
    telegram: settingsCard("Telegram", "telegram", [["api_id", "API ID"], ["api_hash", "API HASH"], ["sources", "群组/频道"], ["history_limit", "历史搜索条数"]]),
    tmdb: settingsCard("TMDB", "tmdb", [["api_key", "API Key"]]),
    proxy: settingsCard("代理设置", "proxy", [["url", "代理地址"], ["modules", "启用代理的模块"]]),
    tg_bot: settingsCard("TG Bot", "tg_bot", [["bot_token", "Bot Token"], ["bot_username", "机器人用户名"], ["allowed_chat_id", "允许的 Chat ID"]]),
    emby: settingsCard("媒体库", "emby", [["server_url", "Emby 地址"], ["api_key", "API Key"]]),
  };
  $("#view").innerHTML = `
    <nav class="settings-tabs">
      ${tabs.map(([key, label]) => `<button class="${state.settingsTab === key ? "active" : ""}" data-settings-tab="${key}">${label}</button>`).join("")}
    </nav>
    <div class="settings settings-single">${cards[state.settingsTab]}</div>
  `;
  document.querySelectorAll("[data-settings-tab]").forEach((btn) => btn.addEventListener("click", () => {
    state.settingsTab = btn.dataset.settingsTab;
    renderSettings();
  }));
  document.querySelectorAll("[data-save-settings]").forEach((form) => form.addEventListener("submit", saveSettings));
  enhanceIntegrationCards();
}

function settingsCard(title, key, fields) {
  const value = state.settings[key]?.value || {};
  return `<form class="card form-grid" data-save-settings="${key}">
    <h3>${title}</h3>
    ${fields.map(([name, label, fallback = "", type = "text"]) => fieldHtml(key, name, label, value[name] || fallback || "", type)).join("")}
    <button type="submit">保存</button>
  </form>`;
}

function fieldHtml(key, name, label, current, type = "text") {
  if (key === "delivery" && name === "mode") {
    const selected = current || "115";
    return `<label>${label}<select name="mode">
      <option value="115" ${selected === "115" ? "selected" : ""}>转存到 115</option>
      <option value="telegram_bot" ${selected === "telegram_bot" ? "selected" : ""}>发送到 TG Bot</option>
    </select></label>`;
  }
  if (key === "proxy" && name === "modules") {
    const selected = Array.isArray(current) ? current : String(current || "").split(",").filter(Boolean);
    const options = [["tmdb", "TMDB"], ["telegram", "Telegram"], ["pan115", "115 网盘"], ["emby", "Emby"]];
    return `<fieldset class="check-group"><legend>${label}</legend>
      ${options.map(([value, text]) => `<label><input type="checkbox" name="modules" value="${value}" ${selected.includes(value) ? "checked" : ""} /> ${text}</label>`).join("")}
    </fieldset>`;
  }
  if (key === "telegram" && name === "sources") {
    const selected = String(current || "").split(",").filter(Boolean);
    return `<fieldset class="check-group" id="telegramSources"><legend>${label}</legend>
      <div class="muted">登录 Telegram 后点击加载列表，然后勾选要监控的群组/频道。</div>
      <button type="button" class="secondary" id="loadTelegramDialogs">加载群组/频道</button>
      <div class="dialog-list" id="telegramDialogList" data-selected="${selected.join(",")}"></div>
    </fieldset>`;
  }
  return `<label>${label}<input type="${type}" name="${name}" value="${current}" /></label>`;
}

async function saveSettings(event) {
  event.preventDefault();
  const key = event.currentTarget.dataset.saveSettings;
  const value = Object.fromEntries(new FormData(event.currentTarget));
  const moduleValues = new FormData(event.currentTarget).getAll("modules");
  if (key === "proxy") value.modules = moduleValues;
  const sourceValues = new FormData(event.currentTarget).getAll("sources");
  if (key === "telegram") value.sources = sourceValues.join(",");
  if (key === "credentials") {
    await api("/api/auth/credentials", { method: "PUT", body: JSON.stringify(value) });
    state.user = await api("/api/auth/me");
  } else {
    await api(`/api/settings/${key}`, { method: "PUT", body: JSON.stringify({ value }) });
    state.settings = await api("/api/settings");
  }
  toast("已保存");
}

function enhanceIntegrationCards() {
  const pan = document.querySelector('[data-save-settings="115"]');
  if (pan) {
    pan.insertAdjacentHTML("beforeend", `
      <label>扫码登录渠道
        <select id="panQrChannel">
          <option value="web">115生活_网页端 - web</option>
          <option value="ios">115生活_苹果端 - ios</option>
          <option value="115ios">115_苹果端 - 115ios</option>
          <option value="android">115生活_安卓端 - android</option>
          <option value="115android">115_安卓端 - 115android</option>
          <option value="ipad">115生活_苹果平板端 - ipad</option>
          <option value="alipaymini">115生活_支付宝小程序 - alipaymini</option>
        </select>
      </label>
      <div class="inline-actions">
        <button type="button" class="secondary" id="panQrBtn">115 扫码</button>
        <button type="button" class="secondary" id="panStatusBtn">检查状态</button>
      </div>
      <div class="qr-box" id="panQrBox">尚未生成二维码</div>
    `);
    $("#panQrBtn").addEventListener("click", startPanQr);
    $("#panStatusBtn").addEventListener("click", checkPanStatus);
  }
  const tg = document.querySelector('[data-save-settings="telegram"]');
  if (tg) {
    tg.insertAdjacentHTML("beforeend", `
      <div class="inline-actions">
        <button type="button" class="secondary" id="tgQrBtn">TG 扫码</button>
        <button type="button" class="secondary" id="tgStatusBtn">检查状态</button>
      </div>
      <label>两步验证密码 <input id="tgPassword" type="password" /></label>
      <button type="button" class="secondary" id="tgPasswordBtn">提交密码</button>
      <div class="qr-box" id="tgQrBox">尚未生成二维码</div>
    `);
    $("#tgQrBtn").addEventListener("click", startTgQr);
    $("#tgStatusBtn").addEventListener("click", checkTgStatus);
    $("#tgPasswordBtn").addEventListener("click", submitTgPassword);
  }
  const loadDialogs = $("#loadTelegramDialogs");
  if (loadDialogs) loadDialogs.addEventListener("click", loadTelegramDialogs);
  const proxyForm = document.querySelector('[data-save-settings="proxy"]');
  if (proxyForm) {
    proxyForm.insertAdjacentHTML("beforeend", `
      <button type="button" class="secondary" id="proxyTestBtn">测试 GitHub / Google 延迟</button>
      <div class="proxy-test-result" id="proxyTestResult"></div>
    `);
    $("#proxyTestBtn").addEventListener("click", testProxyLatency);
  }
}

async function startPanQr() {
  const channel = $("#panQrChannel")?.value || "web";
  const data = await api("/api/115/qr-login", { method: "POST", body: JSON.stringify({ channel }) });
  $("#panQrBox").innerHTML = `<img alt="115 QR" src="${data.qr_url}" /><span>打开 115 App 扫码确认后点击检查状态</span>`;
}

async function checkPanStatus() {
  const data = await api("/api/115/status");
  toast(`115 状态：${data.status}`);
  if (data.status === "authorized") {
    state.settings = await api("/api/settings");
    renderSettings();
  }
}

async function startTgQr() {
  const data = await api("/api/telegram/qr-login", { method: "POST" });
  const qr = encodeURIComponent(data.url);
  $("#tgQrBox").innerHTML = `<img alt="Telegram QR" src="/api/qr?data=${qr}" /><span>用 Telegram 扫码登录，必要时提交两步验证密码</span>`;
}

async function checkTgStatus() {
  const data = await api("/api/telegram/status");
  toast(data.authorized ? "Telegram 已登录" : `Telegram 未登录：${data.status || "waiting"}`);
}

async function submitTgPassword() {
  const password = $("#tgPassword").value;
  if (!password) return toast("请输入两步验证密码");
  await api("/api/telegram/password", { method: "POST", body: JSON.stringify({ password }) });
  toast("密码已提交");
}

async function loadTelegramDialogs() {
  const box = $("#telegramDialogList");
  box.innerHTML = `<div class="muted">正在读取...</div>`;
  const selected = new Set((box.dataset.selected || "").split(",").filter(Boolean));
  const data = await api("/api/telegram/dialogs");
  const dialogs = data.dialogs || [];
  box.innerHTML = dialogs.length ? dialogs.map((item) => `
    <label>
      <input type="checkbox" name="sources" value="${item.source}" ${selected.has(item.source) ? "checked" : ""} />
      <span>${item.title}</span>
      <small>${item.type}${item.username ? ` · @${item.username}` : ""}</small>
    </label>
  `).join("") : `<div class="muted">没有读取到群组/频道，请确认 Telegram 已登录。</div>`;
}

async function testProxyLatency() {
  const form = document.querySelector('[data-save-settings="proxy"]');
  const formData = new FormData(form);
  const url = formData.get("url") || "";
  const modules = formData.getAll("modules");
  const resultBox = $("#proxyTestResult");
  resultBox.innerHTML = `<div class="muted">正在测试...</div>`;
  try {
    const data = await api("/api/proxy/test", { method: "POST", body: JSON.stringify({ url, modules }) });
    const github = data.results.github;
    const google = data.results.google;
    resultBox.innerHTML = `
      <div class="latency-row"><strong>GitHub</strong><span>${github.ok ? `${github.latency_ms} ms` : github.error}</span></div>
      <div class="latency-row"><strong>Google</strong><span>${google.ok ? `${google.latency_ms} ms` : google.error}</span></div>
    `;
  } catch (error) {
    resultBox.innerHTML = `<div class="muted">${error.message}</div>`;
  }
}

boot();
