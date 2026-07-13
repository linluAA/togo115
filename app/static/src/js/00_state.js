const VIEW_KEYS = ["tmdb", "emby", "subscriptions", "logs", "settings"];
const SETTINGS_TAB_KEYS = ["credentials", "delivery", "115", "telegram", "tmdb", "proxy", "rss_sources", "tg_bot", "emby", "backup"];
const TMDB_MORE_MIN_PAGE_SIZE = 40;
const BUILTIN_RSS_PLUGINS = new Set(["bt1207", "qmp4", "hdhive"]);
const BUILTIN_RSS_SOURCES = [
  { id: "builtin_bt1207", name: "BT1207", type: "site_plugin", plugin: "bt1207", url: "https://bt1207to.cc/", enabled: true, use_proxy: false, priority: -50, refresh_interval: 30, test_query: "" },
  { id: "builtin_qmp4", name: "QMP4 / 七味", type: "site_plugin", plugin: "qmp4", url: "https://www.qmp4.com/", enabled: true, use_proxy: false, priority: -50, refresh_interval: 30, test_query: "" },
  { id: "builtin_hdhive", name: "HDHive / 影巢", type: "site_plugin", plugin: "hdhive", url: "https://hdhive.com/", enabled: false, use_proxy: false, priority: -40, refresh_interval: 30, test_query: "tv:86344", points_threshold: 0, browser_path: "", browser_user_data_dir: "" },
];

const state = {
  user: null,
  view: initialView(),
  settings: {},
  subscriptions: [],
  resources: [],
  failedTasks: [],
  sourceStats: [],
  mediaPayloads: new Map(),
  tmdbSearch: [],
  tmdbSearchQuery: "",
  tmdbMore: null,
  tmdbTrending: null,
  tmdbTrendingLimit: 0,
  theme: initialTheme(),
  logsMode: "simple",
  logs: [],
  logsHasMore: false,
  resourcesLimit: 40,
  settingsTab: initialSettingsTab(),
  userMenuOpen: false,
  subscriptionType: "all",
  subscriptionStatus: "all",
  subscriptionCancelMode: false,
  selectedSubscriptionIds: new Set(),
  resourceDeleteMode: false,
  selectedResourceIds: new Set(),
  subscriptionsEmbySynced: false,
  sidebarCollapsed: localStorage.getItem("sidebarCollapsed") === "true",
  rssSourceExpanded: new Set(),
  builtinRssSourceExpanded: new Set(),
  panQrTimer: null,
  tgLoginTimer: null,
  backupText: "",
  panFolder: { cid: "0", path: "/" },
  subscriptionRefreshTimer: null,
};

const navItems = [
  ["tmdb", "TMDB", "片单", "TM"],
  ["emby", "Emby", "媒体库", "Em"],
  ["subscriptions", "订阅", "追新", "订"],
  ["logs", "日志", "事件", "Log"],
  ["settings", "设置", "配置", "设"],
];

const $ = (selector) => document.querySelector(selector);

function routeView() {
  const view = window.location.hash.replace(/^#\/?/, "");
  return VIEW_KEYS.includes(view) ? view : "";
}

function initialView() {
  const stored = localStorage.getItem("currentView") || "";
  return routeView() || (VIEW_KEYS.includes(stored) ? stored : "tmdb");
}

function initialSettingsTab() {
  const stored = localStorage.getItem("settingsTab") || "";
  return SETTINGS_TAB_KEYS.includes(stored) ? stored : "credentials";
}

function initialTheme() {
  return localStorage.getItem("theme") === "light" ? "light" : "dark";
}

function applyTheme() {
  document.documentElement.dataset.theme = state.theme;
}

function toggleTheme() {
  state.theme = state.theme === "light" ? "dark" : "light";
  localStorage.setItem("theme", state.theme);
  applyTheme();
  renderApp();
}

function persistView() {
  if (!VIEW_KEYS.includes(state.view)) state.view = "tmdb";
  localStorage.setItem("currentView", state.view);
  const hash = `#${state.view}`;
  if (window.location.hash !== hash) history.replaceState(null, "", hash);
}

function setView(view) {
  if (!VIEW_KEYS.includes(view)) return;
  state.view = view;
  state.userMenuOpen = false;
  persistView();
  renderApp();
}

applyTheme();

window.addEventListener("hashchange", () => {
  const view = routeView();
  if (!view || view === state.view) return;
  state.view = view;
  localStorage.setItem("currentView", view);
  state.userMenuOpen = false;
  if (state.user) renderApp();
});

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
  const timeoutMs = options.timeoutMs || 12000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const { timeoutMs: _timeoutMs, ...fetchOptions } = options;
  let res;
  try {
    res = await fetch(path, {
      signal: controller.signal,
      ...fetchOptions,
      headers: { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
    });
  } catch (error) {
    if (error.name === "AbortError") throw new Error("请求超时，请稍后刷新");
    throw error;
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let message = res.statusText;
    try { message = (await res.json()).detail || message; } catch {}
    throw new Error(message);
  }
  return res.status === 204 ? null : res.json();
}

async function apiOptional(path, fallback, options = {}) {
  try {
    return await api(path, options);
  } catch {
    return fallback;
  }
}

async function apiQuick(path, fallback, options = {}) {
  return apiOptional(path, fallback, { timeoutMs: 5000, ...options });
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
    state.user = await api("/api/auth/me", { timeoutMs: 6000 });
    renderApp();
    await refreshBase();
    renderApp();
  } catch {
    renderLogin();
  }
}

async function refreshBase() {
  const [settings, subscriptions, resources, failedTasks, sourceStats] = await Promise.all([
    apiQuick("/api/settings", state.settings || {}),
    apiQuick("/api/subscriptions", state.subscriptions || []),
    apiQuick("/api/resources?limit=80", state.resources || []),
    apiQuick("/api/tasks/failed", state.failedTasks || []),
    apiQuick("/api/source-stats", state.sourceStats || []),
  ]);
  state.settings = settings || {};
  state.subscriptions = subscriptions || [];
  state.resources = resources || [];
  state.failedTasks = failedTasks || [];
  state.sourceStats = sourceStats || [];
}

async function refreshSubscriptionData() {
  const [subscriptions, resources, failedTasks] = await Promise.all([
    apiQuick("/api/subscriptions", state.subscriptions || []),
    apiQuick("/api/resources?limit=80", state.resources || []),
    apiQuick("/api/tasks/failed", state.failedTasks || []),
  ]);
  state.subscriptions = subscriptions || [];
  state.resources = resources || [];
  state.failedTasks = failedTasks || [];
}

function scheduleSubscriptionSoftRefresh(delay = 5000) {
  if (state.subscriptionRefreshTimer) clearTimeout(state.subscriptionRefreshTimer);
  state.subscriptionRefreshTimer = setTimeout(async () => {
    state.subscriptionRefreshTimer = null;
    if (state.view !== "subscriptions") return;
    try {
      await refreshSubscriptionData();
      if (state.view === "subscriptions") renderSubscriptions();
    } catch {
      // 搜索期间接口偶发繁忙时跳过本轮软刷新，避免影响当前页面操作。
    }
  }, delay);
}
