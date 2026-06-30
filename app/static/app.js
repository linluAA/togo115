const state = {
  user: null,
  view: "tmdb",
  settings: {},
  subscriptions: [],
  resources: [],
  mediaPayloads: new Map(),
  tmdbSearch: [],
  tmdbMore: null,
  logsMode: "simple",
  settingsTab: "credentials",
  subscriptionType: "all",
  subscriptionStatus: "all",
  subscriptionCancelMode: false,
  selectedSubscriptionIds: new Set(),
  subscriptionsEmbySynced: false,
  sidebarCollapsed: localStorage.getItem("sidebarCollapsed") === "true",
  panQrTimer: null,
  tgLoginTimer: null,
  panFolder: { cid: "0", path: "/" },
};

const navItems = [
  ["tmdb", "TMDB 榜单", "热门剧集和电影，点一下就能订阅", "TM"],
  ["emby", "Emby 看板", "媒体数量、媒体库、用户与观看历史", "Em"],
  ["subscriptions", "我的订阅", "管理剧集和电影追新规则", "订"],
  ["logs", "日志", "查看运行状态和调试信息", "Log"],
  ["settings", "设置", "账号、115、Telegram、TMDB、代理和媒体库", "设"],
];

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function telegramDialogLabels() {
  try {
    return JSON.parse(localStorage.getItem("telegramDialogLabels") || "{}");
  } catch {
    return {};
  }
}

function rememberTelegramDialogs(dialogs) {
  const labels = telegramDialogLabels();
  dialogs.forEach((item) => {
    if (item.source) labels[item.source] = item.title || item.username || item.source;
  });
  localStorage.setItem("telegramDialogLabels", JSON.stringify(labels));
}

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
    <div class="shell ${state.sidebarCollapsed ? "sidebar-collapsed" : ""}">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-mark">115</div>
          <div class="brand-copy"><strong>ToGo115</strong><span>资源订阅系统</span></div>
        </div>
        <nav class="nav">
          ${navItems.map(([key, label, description, icon]) => `<button class="${state.view === key ? "active" : ""}" data-view="${key}" title="${label}">
            <span class="nav-icon">${icon}</span>
            <span class="nav-copy"><strong>${label}</strong><small>${description}</small></span>
          </button>`).join("")}
        </nav>
        <button type="button" class="sidebar-toggle" id="sidebarToggle" aria-label="${state.sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"}">${state.sidebarCollapsed ? "›" : "‹"}</button>
      </aside>
      <main class="main">
        <header class="topbar">
          <div class="topbar-title"><h2>${current[1]}</h2><p>${current[2]}</p></div>
          <div class="top-actions">
            <button class="secondary" id="quickLogBtn">实时日志</button>
            <span class="user-chip">${escapeHtml(state.user?.username || "用户")}</span>
            <button class="secondary" id="logoutBtn">退出</button>
          </div>
        </header>
        <div id="view"></div>
      </main>
    </div>
  `;
  document.querySelectorAll("[data-view]").forEach((btn) => btn.addEventListener("click", () => {
    state.view = btn.dataset.view;
    renderApp();
  }));
  $("#sidebarToggle").addEventListener("click", () => {
    state.sidebarCollapsed = !state.sidebarCollapsed;
    localStorage.setItem("sidebarCollapsed", String(state.sidebarCollapsed));
    renderApp();
  });
  $("#quickLogBtn").addEventListener("click", () => {
    state.view = "logs";
    renderApp();
  });
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

function sectionTitle(type) {
  return type === "movie" ? "热门电影" : "热门剧集";
}

async function renderTmdb() {
  const root = $("#view");
  if (state.tmdbMore) {
    root.innerHTML = `
      <section class="toolbar compact-toolbar">
        <button class="secondary" id="backToTmdb">返回榜单</button>
      </section>
      <section class="section"><h3>${sectionTitle(state.tmdbMore.type)}</h3>${mediaGrid(state.tmdbMore.items, state.tmdbMore.type, { limit: 40, more: false })}</section>
    `;
    $("#backToTmdb").addEventListener("click", () => {
      state.tmdbMore = null;
      renderTmdb();
    });
    bindMediaActions(root);
    return;
  }
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
      ${mediaGrid(tv, "tv", { limit: 13, more: true })}
      <h3>热门电影</h3>
      ${mediaGrid(movie, "movie", { limit: 13, more: true })}
    `;
    bindMediaActions(root);
  } catch (error) {
    $("#trendingSection").innerHTML = `<div class="empty">TMDB 未配置或暂时不可用。配置 API Key 后可搜索和订阅。</div>`;
  }
}

function mediaGrid(items, type, options = {}) {
  if (!items.length) return `<div class="empty">暂无数据，配置 TMDB API Key 后会显示榜单。</div>`;
  const limit = options.limit || 20;
  const visibleItems = items.slice(0, limit);
  const cards = visibleItems.map((item) => {
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
  }).join("");
  const more = options.more ? `<button class="more-card" data-more="${type}" aria-label="查看更多"><span class="arrow">→</span><span class="more-text">查看更多</span></button>` : "";
  return `<div class="media-grid">${cards}${more}</div>`;
}

function bindMediaActions(root = document) {
  root.querySelectorAll("[data-subscribe]").forEach((btn) => btn.addEventListener("click", async (event) => {
    event.stopPropagation();
    const item = state.mediaPayloads.get(btn.dataset.subscribe);
    await subscribeMedia(item);
  }));
  root.querySelectorAll("[data-detail]").forEach((btn) => btn.addEventListener("click", () => showMediaDetail(btn.dataset.detail)));
  root.querySelectorAll("[data-more]").forEach((btn) => btn.addEventListener("click", async () => {
    const type = btn.dataset.more;
    const data = await api("/api/tmdb/trending");
    state.tmdbMore = { type, items: data[type] || [] };
    renderTmdb();
  }));
}

async function subscribeMedia(item) {
  if (!item) return;
  const payload = { ...item };
  if (payload.media_type === "tv" && payload.tmdb_id && !payload.tmdb_total_count) {
    try {
      const detail = await api(`/api/tmdb/${payload.media_type}/${payload.tmdb_id}`);
      payload.tmdb_total_count = detail.number_of_episodes || 0;
      payload.overview = payload.overview || detail.overview || "";
      payload.poster_url = payload.poster_url || posterUrl(detail);
    } catch {}
  }
  await api("/api/subscriptions", { method: "POST", body: JSON.stringify(payload) });
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
  if (payload.media_type === "tv") {
    payload.tmdb_total_count = detail.number_of_episodes || payload.tmdb_total_count || 0;
  }
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
  const movieCount = data.movie_count ?? data.counts?.MovieCount ?? 0;
  const seriesCount = data.series_count ?? data.counts?.SeriesCount ?? 0;
  root.innerHTML = `
    ${data.error ? `<div class="empty">Emby 数据获取失败：${data.error}</div>` : ""}
    <section class="stats">
      <div class="stat"><span>媒体总数</span><b>${data.media_count || 0}</b></div>
      <div class="stat"><span>电视剧</span><b>${seriesCount}</b></div>
      <div class="stat"><span>电影</span><b>${movieCount}</b></div>
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
  return `<div class="emby-grid ${kind === "library" ? "emby-library-grid" : ""}">${items.map((item) => {
    const fallback = kind === "user" ? "" : `<div class="emby-placeholder">媒体</div>`;
    const image = kind === "user"
      ? ""
      : (item.image_url ? `<img class="library-image" src="${item.image_url}" alt="${item.name || item.title || "Emby"}" onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'emby-placeholder', textContent:'媒体'}))" />` : fallback);
    const metaClass = kind === "library" ? "emby-library-meta" : "";
    const description = kind === "library" ? "" : (item.description || item.collection_type || item.date_played || "");
    return `<article class="emby-card ${kind === "library" ? "emby-library-card" : ""}">
      ${image}
      <div class="${metaClass}">
        <h3>${item.name || item.title || "项目"}</h3>
        ${description ? `<p>${description}</p>` : ""}
      </div>
    </article>`;
  }).join("")}</div>`;
}

async function renderSubscriptions() {
  if (!state.subscriptionsEmbySynced) {
    state.subscriptionsEmbySynced = true;
    $("#view").innerHTML = `<div class="empty">正在同步订阅入库状态...</div>`;
    try {
      const result = await api("/api/subscriptions/sync-emby", { method: "POST" });
      if (result?.updated) {
        state.subscriptions = await api("/api/subscriptions");
      }
    } catch {
      // The manual sync button still exposes the error to the user when needed.
    }
  }
  $("#view").innerHTML = `
    ${subscriptionCards()}
    <section class="section">
      <h3>最近发现的资源</h3>
      ${resourceTable()}
    </section>
  `;
  const typeFilter = $("#subscriptionTypeFilter");
  const statusFilter = $("#subscriptionStatusFilter");
  if (typeFilter) typeFilter.addEventListener("change", () => {
    state.subscriptionType = typeFilter.value;
    renderSubscriptions();
  });
  if (statusFilter) statusFilter.addEventListener("change", () => {
    state.subscriptionStatus = statusFilter.value;
    renderSubscriptions();
  });
  $("#subscriptionReset")?.addEventListener("click", () => {
    state.subscriptionType = "all";
    state.subscriptionStatus = "all";
    renderSubscriptions();
  });
  $("#syncEmbySubscriptions")?.addEventListener("click", async () => {
    try {
      const result = await api("/api/subscriptions/sync-emby", { method: "POST" });
      await refreshBase();
      renderSubscriptions();
      toast(result.ok ? `媒体库同步完成，匹配 ${result.matched || 0} 个订阅` : `媒体库同步失败：${result.error || "请查看日志"}`);
    } catch (error) {
      toast(`媒体库同步失败：${error.message}`);
    }
  });
  $("#searchAllSubscriptions")?.addEventListener("click", async () => {
    const button = $("#searchAllSubscriptions");
    button.disabled = true;
    button.textContent = "搜索中";
    try {
      const result = await api("/api/subscriptions/search-all", { method: "POST" });
      await refreshBase();
      renderSubscriptions();
      toast(`搜索完成，检查 ${result.searched || 0} 个订阅，新增 ${result.count || 0} 条资源`);
    } catch (error) {
      button.disabled = false;
      button.textContent = "搜索全部";
      toast(`搜索失败：${error.message}`);
    }
  });
  $("#toggleCancelSubscriptions")?.addEventListener("click", () => {
    state.subscriptionCancelMode = !state.subscriptionCancelMode;
    state.selectedSubscriptionIds.clear();
    renderSubscriptions();
  });
  $("#confirmCancelSubscriptions")?.addEventListener("click", async () => {
    const ids = [...state.selectedSubscriptionIds];
    if (!ids.length) return toast("请选择需要取消的订阅");
    await api("/api/subscriptions/bulk-delete", { method: "POST", body: JSON.stringify({ ids }) });
    state.subscriptionCancelMode = false;
    state.selectedSubscriptionIds.clear();
    await refreshBase();
    renderSubscriptions();
    toast(`已取消 ${ids.length} 个订阅`);
  });
  document.querySelectorAll("[data-select-subscription]").forEach((btn) => btn.addEventListener("change", () => {
    const id = Number(btn.dataset.selectSubscription);
    if (btn.checked) state.selectedSubscriptionIds.add(id);
    else state.selectedSubscriptionIds.delete(id);
  }));
  document.querySelectorAll("[data-delete]").forEach((btn) => btn.addEventListener("click", async () => {
    state.subscriptionCancelMode = true;
    state.selectedSubscriptionIds = new Set([Number(btn.dataset.delete)]);
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

function subscriptionCards() {
  if (!state.subscriptions.length) return `<div class="empty">还没有订阅。可以从 TMDB 榜单或搜索结果里添加。</div>`;
  const filtered = state.subscriptions.filter((item) => {
    const matchType = state.subscriptionType === "all" || item.media_type === state.subscriptionType;
    const matchStatus = state.subscriptionStatus === "all" || item.status === state.subscriptionStatus;
    return matchType && matchStatus;
  });
  const cards = filtered.map((item) => {
      const embyCount = item.emby_count || 0;
      const tmdbTotal = item.tmdb_total_count || 0;
      const library = item.media_type === "movie"
        ? (item.in_library ? "已入库" : "未入库")
        : (item.in_library
          ? (tmdbTotal ? `${embyCount}/${tmdbTotal} 集` : `已入库 ${embyCount} 集`)
          : "未入库");
      const poster = item.poster_url || posterUrl({});
      const keywords = (item.keywords || []).join(", ") || "未设置关键词";
      const completed = item.status === "completed" || (item.media_type === "movie"
        ? Boolean(item.in_library)
        : Boolean(tmdbTotal && embyCount >= tmdbTotal));
      const statusText = completed ? "订阅完成" : (item.status === "active" ? "订阅中" : "已暂停");
      const statusClass = completed ? "completed" : (item.status === "active" ? "active" : "paused");
      const checked = state.selectedSubscriptionIds.has(item.id) ? "checked" : "";
      return `<article class="subscription-card ${state.subscriptionCancelMode ? "selecting" : ""}">
        ${state.subscriptionCancelMode ? `<label class="subscription-select"><input type="checkbox" data-select-subscription="${item.id}" ${checked} /><span></span></label>` : ""}
        <div class="subscription-poster">
          <img src="${escapeHtml(poster)}" alt="${escapeHtml(item.title)}" />
          <div class="subscription-badges">
            <span class="subscription-badge">${item.media_type === "tv" ? "电视剧" : "电影"}</span>
            <span class="subscription-badge ${statusClass}">${statusText}</span>
          </div>
        </div>
        <div class="subscription-info">
          <h3>${escapeHtml(item.title)}</h3>
          <div class="subscription-meta-row">
            <span>${escapeHtml(library)}</span>
            <button type="button" class="keyword-chip" data-edit="${item.id}" title="${escapeHtml(keywords)}">关键词</button>
          </div>
        </div>
      </article>`;
    }).join("");
  return `<section class="subscription-panel">
    <div class="subscription-toolbar">
      <div>
        <h3>我的订阅</h3>
        <p>${state.subscriptions.length} 个订阅，当前显示 ${filtered.length} 个</p>
      </div>
      <div class="subscription-controls">
        <div class="control-group filter-group">
          <select id="subscriptionTypeFilter" aria-label="订阅类型">
            <option value="all" ${state.subscriptionType === "all" ? "selected" : ""}>全部类型</option>
            <option value="tv" ${state.subscriptionType === "tv" ? "selected" : ""}>电视剧</option>
            <option value="movie" ${state.subscriptionType === "movie" ? "selected" : ""}>电影</option>
          </select>
          <select id="subscriptionStatusFilter" aria-label="订阅状态">
            <option value="all" ${state.subscriptionStatus === "all" ? "selected" : ""}>全部状态</option>
            <option value="active" ${state.subscriptionStatus === "active" ? "selected" : ""}>订阅中</option>
            <option value="paused" ${state.subscriptionStatus === "paused" ? "selected" : ""}>已暂停</option>
            <option value="completed" ${state.subscriptionStatus === "completed" ? "selected" : ""}>订阅完成</option>
          </select>
          <button type="button" class="secondary" id="subscriptionReset">重置</button>
        </div>
        <div class="control-group action-group">
          <button type="button" class="secondary" id="searchAllSubscriptions">搜索全部</button>
          <button type="button" class="secondary" id="syncEmbySubscriptions">同步媒体库</button>
          <button type="button" class="danger" id="toggleCancelSubscriptions">${state.subscriptionCancelMode ? "退出取消" : "取消订阅"}</button>
          ${state.subscriptionCancelMode ? `<button type="button" class="danger" id="confirmCancelSubscriptions">确定移除</button>` : ""}
        </div>
      </div>
    </div>
    ${filtered.length ? `<div class="subscription-grid">${cards}</div>` : `<div class="empty">当前筛选没有订阅。</div>`}
  </section>`;
}

function resourceTable() {
  if (!state.resources.length) return `<div class="empty">还没有发现资源链接。</div>`;
  return `<table class="table">
    <thead><tr><th>订阅</th><th>链接</th><th>来源</th><th>状态</th><th>操作</th></tr></thead>
    <tbody>${state.resources.map((item) => `<tr>
      <td data-label="订阅">${item.subscription_title}</td>
      <td data-label="链接"><a href="${item.url}" target="_blank" rel="noreferrer">${item.url}</a></td>
      <td data-label="来源">${item.source}<br><span class="muted">${item.message_id || ""}</span></td>
      <td data-label="状态"><span class="pill">${item.status}</span></td>
      <td data-label="操作"><button class="secondary" data-deliver="${item.id}">重试</button></td>
    </tr>`).join("")}</tbody>
  </table>`;
}

async function renderLogs() {
  const root = $("#view");
  root.innerHTML = `
    <section class="log-toolbar">
      <span class="log-status">● 已连接</span>
      <input id="logFilter" placeholder="输入过滤关键字" />
      <button class="${state.logsMode === "simple" ? "active" : ""}" data-mode="simple">重要</button>
      <button class="${state.logsMode === "debug" ? "active" : ""}" data-mode="debug">全部</button>
      <button class="danger" id="clearLogView">清空</button>
    </section>
    <div class="log-terminal"><div class="log-list"><div class="empty">正在读取日志...</div></div></div>
  `;
  root.querySelectorAll("[data-mode]").forEach((btn) => btn.addEventListener("click", () => {
    state.logsMode = btn.dataset.mode;
    renderLogs();
  }));
  const logs = await api(`/api/logs?mode=${state.logsMode}`);
  renderLogRows(logs);
  $("#logFilter").addEventListener("input", () => renderLogRows(logs));
  $("#clearLogView").addEventListener("click", () => {
    root.querySelector(".log-list").innerHTML = "";
  });
}

function renderLogRows(logs) {
  const keyword = $("#logFilter")?.value.trim().toLowerCase() || "";
  const filtered = keyword ? logs.filter((log) => `${log.level} ${log.scope} ${log.message}`.toLowerCase().includes(keyword)) : logs;
  $(".log-list").innerHTML = filtered.length ? filtered.map((log, index) => {
    const time = new Date(log.created_at).toLocaleString();
    return `<div class="log-line ${log.level}">
      <span class="line-no">${index + 1}</span>
      <span class="level">${log.level.toUpperCase()}</span>
      <span class="time">${time}</span>
      <span class="scope">${log.scope}</span>
      <span class="message">${log.message}</span>
    </div>`;
  }).join("") : `<div class="log-empty">暂无日志</div>`;
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
    tg_bot: settingsCard("TG Bot", "tg_bot", [["bot_token", "监听 Bot Token"], ["bot_username", "转发目标机器人用户名"], ["allowed_chat_id", "允许的 Chat ID"]]),
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
  if (key === "115" && name === "target_path") {
    const cid = state.settings["115"]?.value?.target_cid || "0";
    const path = current || "/";
    state.panFolder = { cid: String(cid), path };
    return `<fieldset class="folder-picker"><legend>${label}</legend>
      <div class="folder-current" id="panFolderCurrent">${escapeHtml(path)}</div>
      <input type="hidden" name="target_path" id="panTargetPath" value="${escapeHtml(path)}" />
      <input type="hidden" name="target_cid" id="panTargetCid" value="${escapeHtml(cid)}" />
      <div class="inline-actions">
        <button type="button" class="secondary" id="panFolderRoot">根目录</button>
        <button type="button" class="secondary" id="loadPanFolders">选择目录</button>
      </div>
      <div class="dialog-list folder-list" id="panFolderList"></div>
    </fieldset>`;
  }
  if (key === "115" && name === "qr_login") {
    const status = current || (state.settings["115"]?.value?.cookie ? "已登录" : "未登录");
    return `<label>${label}<input type="text" name="${name}" value="${status}" readonly /></label>`;
  }
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
    const labels = telegramDialogLabels();
    const selectedSummary = selected.length
      ? `<div class="selected-sources">${selected.map((source) => `<span class="source-chip" title="${escapeHtml(source)}">${escapeHtml(labels[source] || source)}</span>`).join("")}</div>
        ${selected.map((source) => `<input type="hidden" name="sources" value="${escapeHtml(source)}" />`).join("")}`
      : `<div class="muted">登录 Telegram 后点击加载列表，然后勾选要监控的群组/频道。</div>`;
    const buttonText = selected.length ? "重新选择群组/频道" : "加载群组/频道";
    const listClass = selected.length ? "dialog-list hidden" : "dialog-list";
    return `<fieldset class="check-group" id="telegramSources"><legend>${label}</legend>
      ${selectedSummary}
      <button type="button" class="secondary" id="loadTelegramDialogs">${buttonText}</button>
      <div class="${listClass}" id="telegramDialogList" data-selected="${escapeHtml(selected.join(","))}"></div>
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
  if (key === "telegram") renderSettings();
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
          <option value="115ipad">115_苹果平板端 - 115ipad</option>
          <option value="alipaymini">115生活_支付宝小程序 - alipaymini</option>
          <option value="wechatmini">115生活_微信小程序 - wechatmini</option>
          <option value="qandroid">115生活_安卓电视端 - qandroid</option>
          <option value="tv">115生活_TV端 - tv</option>
          <option value="mac">115生活_MAC端 - mac</option>
          <option value="windows">115生活_Windows端 - windows</option>
          <option value="linux">115生活_Linux端 - linux</option>
          <option value="harmony">115生活_鸿蒙端 - harmony</option>
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
      <div class="tg-phone-login">
        <label>手机号 <input id="tgPhone" type="tel" placeholder="+8613800000000" autocomplete="tel" /></label>
        <button type="button" class="secondary" id="tgSendCodeBtn">发送验证码</button>
        <label>验证码 <input id="tgCode" inputmode="numeric" autocomplete="one-time-code" /></label>
        <button type="button" class="secondary" id="tgCodeLoginBtn">验证码登录</button>
      </div>
      <div class="tg-password-login hidden" id="tgPasswordPanel">
        <label>两步验证密码 <input id="tgPassword" type="password" /></label>
        <button type="button" class="secondary" id="tgPasswordBtn">提交密码</button>
      </div>
      <div class="qr-box" id="tgQrBox">尚未生成二维码</div>
    `);
    $("#tgQrBtn").addEventListener("click", startTgQr);
    $("#tgStatusBtn").addEventListener("click", checkTgStatus);
    $("#tgSendCodeBtn").addEventListener("click", sendTgCode);
    $("#tgCodeLoginBtn").addEventListener("click", loginTgCode);
    $("#tgPasswordBtn").addEventListener("click", submitTgPassword);
  }
  const loadDialogs = $("#loadTelegramDialogs");
  if (loadDialogs) loadDialogs.addEventListener("click", loadTelegramDialogs);
  const loadFolders = $("#loadPanFolders");
  if (loadFolders) loadFolders.addEventListener("click", () => loadPanFolders(state.panFolder.cid || "0", state.panFolder.path || "/"));
  const folderRoot = $("#panFolderRoot");
  if (folderRoot) folderRoot.addEventListener("click", () => selectPanFolder("0", "/"));
  const proxyForm = document.querySelector('[data-save-settings="proxy"]');
  if (proxyForm) {
    proxyForm.insertAdjacentHTML("beforeend", `
      <button type="button" class="secondary" id="proxyTestBtn">延迟测试</button>
      <div class="proxy-test-result" id="proxyTestResult"></div>
    `);
    $("#proxyTestBtn").addEventListener("click", testProxyLatency);
  }
}

async function startPanQr() {
  const channel = $("#panQrChannel")?.value || "web";
  const box = $("#panQrBox");
  if (state.panQrTimer) clearInterval(state.panQrTimer);
  box.innerHTML = `<span>正在生成二维码...</span>`;
  try {
    const data = await api("/api/115/qr-login", { method: "POST", body: JSON.stringify({ channel }) });
    box.innerHTML = `<img alt="115 QR" src="${data.qr_url}" onerror="this.replaceWith(Object.assign(document.createElement('span'), {textContent:'二维码图片加载失败，请查看日志里的 115 错误'}))" /><span>打开 115 App 扫码确认后点击检查状态</span>`;
    state.panQrTimer = setInterval(checkPanStatus, 3000);
  } catch (error) {
    box.innerHTML = `<span>二维码生成失败：${error.message}</span>`;
  }
}

async function checkPanStatus() {
  const data = await api("/api/115/status");
  const statusText = { "0": "等待扫码", "1": "已扫码，等待确认", "2": "已确认", "-1": "二维码已过期", "-2": "已取消", authorized: "已登录", cookie_missing: "未获取到 Cookie" }[data.status] || data.status;
  const box = $("#panQrBox");
  const statusInput = document.querySelector('[data-save-settings="115"] [name="qr_login"]');
  if (statusInput) statusInput.value = statusText;
  if (box && data.status !== "authorized") {
    const label = box.querySelector(".qr-status-label");
    if (label) label.textContent = `115 状态：${statusText}`;
    else box.insertAdjacentHTML("beforeend", `<span class="qr-status-label">115 状态：${statusText}</span>`);
  }
  if (!state.panQrTimer || data.status === "authorized") toast(`115 状态：${statusText}`);
  if (data.status === "authorized") {
    if (state.panQrTimer) clearInterval(state.panQrTimer);
    state.panQrTimer = null;
    state.settings = await api("/api/settings");
    const cookieInput = document.querySelector('[data-save-settings="115"] [name="cookie"]');
    if (cookieInput && data.cookie) cookieInput.value = data.cookie;
    renderSettings();
    toast("115 Cookie 已自动保存");
  } else if (["-1", "-2", "cookie_missing"].includes(String(data.status))) {
    if (state.panQrTimer) clearInterval(state.panQrTimer);
    state.panQrTimer = null;
  }
}

async function startTgQr() {
  const box = $("#tgQrBox");
  if (state.tgLoginTimer) clearInterval(state.tgLoginTimer);
  box.innerHTML = `<span>正在生成二维码...</span>`;
  try {
    const data = await api("/api/telegram/qr-login", { method: "POST" });
    box.innerHTML = `<img alt="Telegram QR" src="${data.qr_url}" onerror="this.replaceWith(Object.assign(document.createElement('span'), {textContent:'二维码图片加载失败'}))" /><span>用 Telegram 扫码登录</span>`;
    state.tgLoginTimer = setInterval(checkTgStatus, 3000);
  } catch (error) {
    box.innerHTML = `<span>二维码生成失败：${error.message}</span>`;
  }
}

async function checkTgStatus() {
  const data = await api("/api/telegram/status");
  const box = $("#tgQrBox");
  if (data.status === "password_required") {
    if (state.tgLoginTimer) clearInterval(state.tgLoginTimer);
    state.tgLoginTimer = null;
    $("#tgPasswordPanel")?.classList.remove("hidden");
  }
  if (data.authorized) {
    if (state.tgLoginTimer) clearInterval(state.tgLoginTimer);
    state.tgLoginTimer = null;
    if (box) box.innerHTML = `<span>Telegram 已登录</span>`;
  } else if (box && data.status && data.status !== "waiting") {
    const label = box.querySelector(".qr-status-label");
    if (label) label.textContent = `Telegram 状态：${data.status}`;
    else box.insertAdjacentHTML("beforeend", `<span class="qr-status-label">Telegram 状态：${data.status}</span>`);
  }
  if (!state.tgLoginTimer) toast(data.authorized ? "Telegram 已登录" : `Telegram 未登录：${data.status || "waiting"}`);
}

async function sendTgCode() {
  const phone = $("#tgPhone").value.trim();
  if (!phone) return toast("请输入手机号");
  try {
    await api("/api/telegram/send-code", { method: "POST", body: JSON.stringify({ phone }) });
    toast("验证码已发送");
  } catch (error) {
    toast(`验证码发送失败：${error.message}`);
  }
}

async function loginTgCode() {
  const phone = $("#tgPhone").value.trim();
  const code = $("#tgCode").value.trim();
  if (!phone || !code) return toast("请输入手机号和验证码");
  try {
    const data = await api("/api/telegram/code-login", { method: "POST", body: JSON.stringify({ phone, code }) });
    if (data.status === "password_required") {
      $("#tgPasswordPanel")?.classList.remove("hidden");
      toast("请输入两步验证密码");
      return;
    }
    toast("Telegram 已登录");
  } catch (error) {
    toast(`验证码登录失败：${error.message}`);
  }
}

async function submitTgPassword() {
  const password = $("#tgPassword").value;
  if (!password) return toast("请输入两步验证密码");
  try {
    await api("/api/telegram/password", { method: "POST", body: JSON.stringify({ password }) });
    $("#tgPasswordPanel")?.classList.add("hidden");
    toast("Telegram 已登录");
  } catch (error) {
    toast(`两步验证失败：${error.message}`);
  }
}

async function loadTelegramDialogs() {
  const box = $("#telegramDialogList");
  const picker = $("#telegramSources");
  box.classList.remove("hidden");
  box.innerHTML = `<div class="muted">正在读取...</div>`;
  const selected = new Set((box.dataset.selected || "").split(",").filter(Boolean));
  try {
    const status = await api("/api/telegram/status");
    if (!status.authorized) {
      box.innerHTML = `<div class="muted">Telegram 未登录：${status.status || "not_authorized"}</div>`;
      return;
    }
    const data = await api("/api/telegram/dialogs");
    const dialogs = data.dialogs || [];
    rememberTelegramDialogs(dialogs);
    if (dialogs.length) picker?.querySelectorAll('input[type="hidden"][name="sources"]').forEach((input) => input.remove());
    box.innerHTML = dialogs.length ? dialogs.map((item) => `
      <label>
        <input type="checkbox" name="sources" value="${escapeHtml(item.source)}" ${selected.has(item.source) ? "checked" : ""} />
        <span>${escapeHtml(item.title)}</span>
        <small>${escapeHtml(item.type)}${item.username ? ` · @${escapeHtml(item.username)}` : ""}</small>
      </label>
    `).join("") : `<div class="muted">没有读取到群组/频道。</div>`;
  } catch (error) {
    box.innerHTML = `<div class="muted">群组/频道读取失败：${error.message}</div>`;
  }
}

function selectPanFolder(cid, path) {
  state.panFolder = { cid: String(cid), path };
  const pathInput = $("#panTargetPath");
  const cidInput = $("#panTargetCid");
  const current = $("#panFolderCurrent");
  if (pathInput) pathInput.value = path;
  if (cidInput) cidInput.value = cid;
  if (current) current.textContent = path;
  toast(`已选择目录：${path}`);
}

async function loadPanFolders(cid = "0", basePath = "/") {
  const box = $("#panFolderList");
  box.innerHTML = `<div class="muted">正在读取目录...</div>`;
  try {
    const data = await api(`/api/115/folders?cid=${encodeURIComponent(cid)}`);
    const folders = data.folders || [];
    const parent = basePath !== "/" ? `<button type="button" class="folder-row" data-cid="0" data-path="/">返回根目录</button>` : "";
    box.innerHTML = parent + (folders.length ? folders.map((item) => {
      const path = `${basePath.replace(/\/$/, "")}/${item.name}`.replace(/^$/, "/");
      return `<button type="button" class="folder-row" data-cid="${escapeHtml(item.id)}" data-path="${escapeHtml(path)}">${escapeHtml(item.name)}</button>`;
    }).join("") : `<div class="muted">当前目录没有子目录。</div>`);
    box.querySelectorAll(".folder-row").forEach((btn) => btn.addEventListener("click", () => {
      selectPanFolder(btn.dataset.cid, btn.dataset.path);
      loadPanFolders(btn.dataset.cid, btn.dataset.path);
    }));
  } catch (error) {
    box.innerHTML = `<div class="muted">目录读取失败：${error.message}</div>`;
  }
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
