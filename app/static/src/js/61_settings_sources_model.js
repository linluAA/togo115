function rssSourcesValue() {
  const config = rssSourcesConfig();
  return Array.isArray(config.sources) ? config.sources.filter((source) => !isBuiltinRssSource(source)) : [];
}

function rssSourcesConfig() {
  return state.settings.rss_sources?.value || {};
}

function builtinRssOverrides() {
  const value = rssSourcesConfig().builtin_sources;
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function builtinRssSourcesValue() {
  const overrides = builtinRssOverrides();
  const legacySources = Array.isArray(rssSourcesConfig().sources) ? rssSourcesConfig().sources.filter(isBuiltinRssSource) : [];
  const legacyHaisou = state.settings.haisou?.value || {};
  return BUILTIN_RSS_SOURCES.map((source) => {
    const legacy = legacySources.find((item) => normalizeSitePlugin(item) === source.plugin) || {};
    const override = overrides[source.id] || {};
    const migrated = source.plugin === "haisou" && !Object.keys(override).length
      ? {
          api_key: legacyHaisou.api_key || "",
          enabled: legacyHaisou.enabled !== false && Boolean(legacyHaisou.api_key),
          page_size: legacyHaisou.page_size || 20,
          search_in: legacyHaisou.search_in || "title",
          use_proxy: Boolean(legacyHaisou.use_proxy),
        }
      : {};
    return normalizeRssSource({
      ...source,
      ...legacy,
      ...migrated,
      ...override,
      id: source.id,
      name: source.name,
      type: "site_plugin",
      plugin: source.plugin,
      url: source.plugin === "haisou" ? "https://haisou.cc/" : (override.url || legacy.url || source.url),
    });
  });
}

function builtinRssOverrideFromSource(source) {
  const priority = Number.parseInt(source.priority, 10);
  const refreshInterval = Number.parseInt(source.refresh_interval, 10);
  const pageSize = Number.parseInt(source.page_size, 10);
  const base = {
    url: source.url || "",
    enabled: source.enabled !== false,
    use_proxy: Boolean(source.use_proxy),
    keywords: source.keywords || "",
    quality: source.quality || "",
    test_query: source.test_query || "",
    priority: Number.isFinite(priority) ? priority : -50,
    refresh_interval: Math.max(Number.isFinite(refreshInterval) ? refreshInterval : 30, 5),
  };
  if (normalizeSitePlugin(source) !== "haisou") return base;
  return {
    ...base,
    url: "https://haisou.cc/",
    api_key: source.api_key || "",
    page_size: Math.max(1, Math.min(Number.isFinite(pageSize) ? pageSize : 20, 100)),
    search_in: source.search_in === "files" ? "files" : "title",
    match_fuzzy: matchWordsToText(source.match_fuzzy),
    match_exact: matchWordsToText(source.match_exact),
    match_exclude: matchWordsToText(source.match_exclude),
  };
}

function matchWordsToText(value) {
  if (Array.isArray(value)) return value.map((item) => String(item || "").trim()).filter(Boolean).join("\n");
  return String(value || "").trim();
}

function matchTextToWords(value) {
  return String(value || "")
    .replace(/，/g, ",")
    .split(/[\n\r,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeRssSource(source) {
  const plugin = normalizeSitePlugin(source);
  const normalized = {
    ...source,
    id: source.id || `rss_${Date.now()}_${Math.random().toString(16).slice(2)}`,
    enabled: source.enabled !== false,
    type: normalizeRssSourceType(source.type),
    plugin,
    priority: Number.parseInt(source.priority, 10) || 0,
    refresh_interval: Math.max(Number.parseInt(source.refresh_interval, 10) || 30, 5),
    test_query: source.test_query || "",
    keywords: source.keywords || "",
    quality: source.quality || "",
  };
  if (plugin === "haisou") {
    const pageSize = Number.parseInt(source.page_size, 10);
    normalized.url = "https://haisou.cc/";
    normalized.api_key = source.api_key || "";
    normalized.page_size = Math.max(1, Math.min(Number.isFinite(pageSize) ? pageSize : 20, 100));
    normalized.search_in = source.search_in === "files" ? "files" : "title";
    normalized.match_fuzzy = matchWordsToText(source.match_fuzzy);
    normalized.match_exact = matchWordsToText(source.match_exact);
    normalized.match_exclude = matchWordsToText(source.match_exclude);
  }
  return normalized;
}

function ensureRssSourceIds(sources) {
  return sources.map((source, index) => normalizeRssSource({ ...source, id: source.id || `rss_${Date.now()}_${index}_${Math.random().toString(16).slice(2)}` }));
}

function normalizeRssSourceType(type) {
  const value = String(type || "rss").toLowerCase();
  if (["magnet_web", "web_magnet", "magnet", "site", "plugin"].includes(value)) return "site_plugin";
  return value || "rss";
}

function normalizeSitePlugin(source) {
  const url = String(source?.url || "").toLowerCase();
  if (url.includes("haisou.cc") || url.includes("apiok.us/api/b9d1")) return "haisou";
  if (url.includes("qmp4.com")) return "qmp4";
  if (url.includes("bt1207")) return "bt1207";
  const raw = String(source?.plugin || source?.site_plugin || "").toLowerCase();
  if (["haisou", "海搜"].includes(raw)) return "haisou";
  if (["bt1207", "bt1207_magnet"].includes(raw)) return "bt1207";
  if (["qmp4", "qiwei", "qmp4_magnet"].includes(raw)) return "qmp4";
  return "generic_magnet";
}

function isBuiltinRssSource(source) {
  const type = normalizeRssSourceType(source?.type);
  return type === "site_plugin" && BUILTIN_RSS_PLUGINS.has(normalizeSitePlugin(source));
}

function sitePluginLabel(plugin) {
  const normalized = normalizeSitePlugin({ plugin });
  if (normalized === "bt1207") return "BT1207";
  if (normalized === "qmp4") return "QMP4";
  if (normalized === "haisou") return "海搜";
  return "通用磁力站";
}

function rssSourceTypeLabel(type) {
  const value = normalizeRssSourceType(type);
  if (value === "torznab") return "Torznab";
  if (value === "site_plugin") return "站点插件";
  return "RSS";
}

function rssSourceUrlLabel(type, plugin = "generic_magnet") {
  const value = normalizeRssSourceType(type);
  if (value === "site_plugin") {
    const normalized = normalizeSitePlugin({ plugin });
    return "站点首页 / 搜索 URL 模板";
  }
  if (value === "torznab") return "Torznab URL";
  return "RSS URL";
}

function rssSourceUrlPlaceholder(type, plugin = "generic_magnet") {
  const value = normalizeRssSourceType(type);
  if (value === "site_plugin") {
    const normalized = normalizeSitePlugin({ plugin });
    if (normalized === "bt1207") return "例如：https://bt1207to.cc/";
    if (normalized === "qmp4") return "例如：https://www.qmp4.com/";
    if (normalized === "haisou") return "https://haisou.cc/";
    return "例如：https://yhdm33.com/s/{query}.html，也可以只填站点首页";
  }
  if (value === "torznab") return "例如：https://example.com/api?t=search&q={query}";
  return "例如：https://example.com/rss.xml";
}

function rssSourcePriority(source) {
  return Number.parseInt(source.priority, 10) || 0;
}

function sourceStatFor(source) {
  const type = normalizeRssSourceType(source.type);
  const name = source.name || "订阅源";
  const key = `${type}:${name}`;
  return (state.sourceStats || []).find((item) => item.source_key === key || (item.source_name === name && item.source_type === type));
}

function sourceHealthLabel(reason) {
  if (reason === "recent_failures") return "最近失败较多";
  if (reason === "slow_source") return "响应过慢";
  return "状态异常";
}

function sourceHealthChip(stat) {
  if (!stat) return "";
  if (stat.degraded) {
    return `<span class="source-chip-warning">临时降级：${escapeHtml(sourceHealthLabel(stat.degrade_reason))}</span>`;
  }
  return `<span class="source-chip-ok">状态正常</span>`;
}
