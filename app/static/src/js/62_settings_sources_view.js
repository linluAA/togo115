function rssSourcesCard() {
  const sources = ensureRssSourceIds(rssSourcesValue());
  const builtinSources = builtinRssSourcesValue();
  if (!state.settings.rss_sources) state.settings.rss_sources = { value: { sources } };
  else state.settings.rss_sources.value = { ...(state.settings.rss_sources.value || {}), sources };
  return `<form class="card form-grid rss-source-card" data-save-rss-sources>
    <div class="settings-heading">
      <h3>订阅源</h3>
      <button type="button" class="secondary" id="addRssSource">新增订阅源</button>
    </div>
    <div class="builtin-source-panel">
      <div>
        <strong>内置订阅源</strong>
        <span>Telegram 未命中后会自动搜索，可按需启用和调整优先级。</span>
      </div>
      <div class="builtin-source-list">
        ${builtinSources.map((source) => `<button type="button" class="source-chip builtin-source-chip ${state.builtinRssSourceExpanded.has(source.id) ? "active" : ""}" data-toggle-builtin-source="${escapeHtml(source.id)}" title="${escapeHtml(source.url)}">${escapeHtml(source.name)}</button>`).join("")}
      </div>
      <div class="builtin-source-edit-list">
        ${builtinSources.filter((source) => state.builtinRssSourceExpanded.has(source.id)).map(builtinRssSourceItemHtml).join("")}
      </div>
    </div>
    <div class="rss-source-list">
      ${sources.length ? sources.map(rssSourceItemHtml).join("") : `<div class="empty">还没有添加订阅源。</div>`}
    </div>
    <button type="submit">保存</button>
  </form>`;
}

function builtinRssSourceItemHtml(source) {
  const priority = rssSourcePriority(source);
  const interval = Number.parseInt(source.refresh_interval, 10) || 30;
  const testQuery = source.test_query || "";
  const plugin = normalizeSitePlugin(source);
  const stat = sourceStatFor(source);
  const isHaisou = plugin === "haisou";
  const chips = isHaisou
    ? `<span>内置</span>
          <span>海搜 API</span>
          <span>优先级 ${escapeHtml(priority)}</span>
          <span>${escapeHtml(interval)} 分钟</span>
          <span>${source.enabled === false ? "停用" : "启用"}</span>
          <span>${source.use_proxy ? "代理" : "直连"}</span>
          <span>${source.search_in === "files" ? "搜文件名" : "搜标题"}</span>
          ${source.api_key ? `<span>Key 已配置</span>` : `<span>未配置 Key</span>`}
          ${testQuery ? `<span>测试 ${escapeHtml(testQuery)}</span>` : ""}
          ${stat ? `<span>成功率 ${escapeHtml(stat.success_rate || 0)}%</span><span>命中 ${escapeHtml(stat.match_count || 0)}</span><span>${escapeHtml(stat.last_latency_ms || "-")} ms</span>` : ""}`
    : `<span>内置</span>
          <span>${sitePluginLabel(source.plugin)}</span>
          <span>优先级 ${escapeHtml(priority)}</span>
          <span>${escapeHtml(interval)} 分钟</span>
          <span>${source.enabled === false ? "停用" : "启用"}</span>
          <span>${source.use_proxy ? "代理" : "直连"}</span>
          ${testQuery ? `<span>测试 ${escapeHtml(testQuery)}</span>` : ""}
          ${stat ? `<span>成功率 ${escapeHtml(stat.success_rate || 0)}%</span><span>命中 ${escapeHtml(stat.match_count || 0)}</span><span>${escapeHtml(stat.last_latency_ms || "-")} ms</span>` : ""}`;
  return `<section class="rss-source-item builtin-source-item expanded" data-source-id="${escapeHtml(source.id)}" data-builtin-source-id="${escapeHtml(source.id)}">
    <div class="rss-source-title">
      <div class="rss-source-summary">
        <strong>${escapeHtml(source.name)}</strong>
        <span class="rss-source-url-text" title="${escapeHtml(source.url || "")}">${escapeHtml(source.url || "")}</span>
        <div class="rss-source-chips">${chips}</div>
      </div>
      <div class="inline-actions">
        <button type="button" class="secondary" data-toggle-builtin-source="${escapeHtml(source.id)}">收起</button>
        <button type="button" class="secondary" data-test-rss-source="${escapeHtml(source.id)}">测试</button>
      </div>
    </div>
    <div class="rss-source-grid">
      <input type="hidden" class="rss-source-name" value="${escapeHtml(source.name)}" />
      <input type="hidden" class="rss-source-type" value="site_plugin" />
      <input type="hidden" class="rss-source-plugin" value="${escapeHtml(source.plugin)}" />
      ${isHaisou ? haisouBuiltinFields(source, priority, interval, testQuery) : rssSourceCommonFields(source, "site_plugin", plugin, priority, interval, testQuery, true)}
    </div>
    <div class="rss-source-test-result muted hidden" data-rss-test-result="${escapeHtml(source.id)}"></div>
  </section>`;
}

function haisouBuiltinFields(source, priority, interval, testQuery) {
  const pageSize = Number.parseInt(source.page_size, 10) || 20;
  const searchIn = source.search_in === "files" ? "files" : "title";
  return `
    <input type="hidden" class="rss-source-url-input" value="https://haisou.cc/" />
    <label class="rss-source-api-key-field">API Key
      <input class="rss-source-api-key" type="password" autocomplete="off" placeholder="iDataRiver 海搜 API Key" value="${escapeHtml(source.api_key || "")}" />
      <span class="field-hint muted">在 <a href="https://www.idatariver.com/zh-cn/project/haisou-api-b9d1" target="_blank" rel="noopener noreferrer">iDataRiver 海搜 API</a> 购买/开通后，于控制台获取 apikey；请求按次计费。</span>
    </label>
    <label>每页数量 <input class="rss-source-page-size" type="number" min="1" max="100" step="1" value="${escapeHtml(pageSize)}" /></label>
    <label>搜索范围
      <select class="rss-source-search-in">
        <option value="title" ${searchIn === "title" ? "selected" : ""}>标题</option>
        <option value="files" ${searchIn === "files" ? "selected" : ""}>文件名</option>
      </select>
    </label>
    <label>优先级 <input class="rss-source-priority" type="number" step="1" value="${escapeHtml(priority)}" /></label>
    <label>刷新间隔 <input class="rss-source-interval" type="number" min="5" step="1" value="${escapeHtml(interval)}" /></label>
    <label>测试关键字 <input class="rss-source-test-query" placeholder="例如：斗罗大陆" value="${escapeHtml(testQuery)}" /></label>
    <label class="toggle-row"><input class="rss-source-enabled" type="checkbox" ${source.enabled === false ? "" : "checked"} /> 启用此内置源</label>
    <label class="toggle-row"><input class="rss-source-proxy" type="checkbox" ${source.use_proxy ? "checked" : ""} /> 是否启用代理</label>
    <label class="rss-source-filter">关键词过滤 <textarea class="rss-source-keywords" rows="2">${escapeHtml(source.keywords || "")}</textarea></label>
    <label class="rss-source-filter">质量过滤 <textarea class="rss-source-quality" rows="2">${escapeHtml(source.quality || "")}</textarea></label>`;
}

function rssSourceItemHtml(source, index) {
  const type = normalizeRssSourceType(source.type);
  const plugin = normalizeSitePlugin(source);
  const interval = Number.parseInt(source.refresh_interval, 10) || 30;
  const expanded = state.rssSourceExpanded.has(source.id);
  const name = source.name || `订阅源 ${index + 1}`;
  const url = source.url || "未填写 URL";
  const priority = rssSourcePriority(source);
  const keywordCount = splitFilterText(source.keywords).length;
  const qualityCount = splitFilterText(source.quality).length;
  const testQuery = source.test_query || "";
  const stat = sourceStatFor({ ...source, type });
  return `<section class="rss-source-item ${expanded ? "expanded" : "collapsed"}" data-source-id="${escapeHtml(source.id)}">
    <div class="rss-source-title">
      <div class="rss-source-summary">
        <strong>${escapeHtml(name)}</strong>
        <span class="rss-source-url-text" title="${escapeHtml(url)}">${escapeHtml(url)}</span>
        <div class="rss-source-chips">
          <span>${rssSourceTypeLabel(type)}</span>
          ${type === "site_plugin" ? `<span>${sitePluginLabel(plugin)}</span>` : ""}
          <span>优先级 ${escapeHtml(priority)}</span>
          <span>${escapeHtml(interval)} 分钟</span>
          <span>${source.use_proxy ? "代理" : "直连"}</span>
          ${testQuery ? `<span>测试 ${escapeHtml(testQuery)}</span>` : ""}
          ${keywordCount ? `<span>关键词 ${keywordCount}</span>` : ""}
          ${qualityCount ? `<span>质量 ${qualityCount}</span>` : ""}
          ${stat ? `<span>成功率 ${escapeHtml(stat.success_rate || 0)}%</span><span>命中 ${escapeHtml(stat.match_count || 0)}</span><span>${escapeHtml(stat.last_latency_ms || "-")} ms</span>` : ""}
        </div>
      </div>
      <div class="inline-actions">
        <button type="button" class="secondary" data-toggle-rss-source="${escapeHtml(source.id)}">${expanded ? "收起" : "编辑"}</button>
        <button type="button" class="secondary" data-test-rss-source="${escapeHtml(source.id)}">测试</button>
        <button type="button" class="secondary danger-lite" data-remove-rss-source="${escapeHtml(source.id)}">删除</button>
      </div>
    </div>
    <div class="rss-source-grid ${expanded ? "" : "hidden"}">
      <label>源名称 <input class="rss-source-name" value="${escapeHtml(source.name || "")}" /></label>
      <label>类型
        <select class="rss-source-type">
          <option value="rss" ${type === "rss" ? "selected" : ""}>RSS</option>
          <option value="torznab" ${type === "torznab" ? "selected" : ""}>Torznab</option>
          <option value="site_plugin" ${type === "site_plugin" ? "selected" : ""}>站点插件</option>
        </select>
      </label>
      <label class="rss-source-plugin-row ${type === "site_plugin" ? "" : "hidden"}">插件
        <select class="rss-source-plugin">
          <option value="generic_magnet" ${plugin === "generic_magnet" ? "selected" : ""}>通用磁力站</option>
        </select>
      </label>
      ${rssSourceCommonFields(source, type, plugin, priority, interval, testQuery, false)}
    </div>
    <div class="rss-source-test-result muted hidden" data-rss-test-result="${escapeHtml(source.id)}"></div>
  </section>`;
}

function rssSourceCommonFields(source, type, plugin, priority, interval, testQuery, builtin) {
  return `
    <label class="rss-source-url"><span class="rss-source-url-label">${rssSourceUrlLabel(type, plugin)}</span> <input class="rss-source-url-input" placeholder="${rssSourceUrlPlaceholder(type, plugin)}" value="${escapeHtml(source.url || "")}" /></label>
    <label>优先级 <input class="rss-source-priority" type="number" step="1" value="${escapeHtml(priority)}" /></label>
    <label>刷新间隔 <input class="rss-source-interval" type="number" min="5" step="1" value="${escapeHtml(interval)}" /></label>
    <label>测试关键字 <input class="rss-source-test-query" placeholder="例如：斗罗大陆" value="${escapeHtml(testQuery)}" /></label>
    ${builtin ? `<label class="toggle-row"><input class="rss-source-enabled" type="checkbox" ${source.enabled === false ? "" : "checked"} /> 启用此内置源</label>` : ""}
    <label class="toggle-row"><input class="rss-source-proxy" type="checkbox" ${source.use_proxy ? "checked" : ""} /> 是否启用代理</label>
    <label class="rss-source-filter">关键词过滤 <textarea class="rss-source-keywords" rows="3">${escapeHtml(source.keywords || "")}</textarea></label>
    <label class="rss-source-filter">质量过滤 <textarea class="rss-source-quality" rows="3">${escapeHtml(source.quality || "")}</textarea></label>`;
}

function syncRssSourceTypeUi(event) {
  const row = event.currentTarget.closest(".rss-source-item");
  if (!row) return;
  const type = normalizeRssSourceType(row.querySelector(".rss-source-type")?.value || "rss");
  const plugin = row.querySelector(".rss-source-plugin")?.value || "generic_magnet";
  const label = row.querySelector(".rss-source-url-label");
  const input = row.querySelector(".rss-source-url-input");
  const pluginRow = row.querySelector(".rss-source-plugin-row");
  if (label) label.textContent = rssSourceUrlLabel(type, plugin);
  if (input) input.placeholder = rssSourceUrlPlaceholder(type, plugin);
  if (pluginRow) pluginRow.classList.toggle("hidden", type !== "site_plugin");
  if (event.currentTarget.classList.contains("rss-source-plugin")) {
    updateRssSourceDraftFromRow(row, type, plugin);
    renderSettings();
  }
}

function updateRssSourceDraftFromRow(row, type, plugin) {
  const id = row.dataset.sourceId;
  if (!id || row.dataset.builtinSourceId) return;
  const sources = ensureRssSourceIds(rssSourcesValue()).map((source) => {
    if (source.id !== id) return source;
    return { ...source, ...rssSourceFromRow(row, id, source, type, plugin) };
  });
  state.rssSourceExpanded.add(id);
  state.settings.rss_sources = { value: { ...rssSourcesConfig(), sources } };
}

function rssSourceFromRow(row, id, original, type, plugin) {
  const refreshInterval = Number.parseInt(row.querySelector(".rss-source-interval")?.value || "30", 10);
  const priority = Number.parseInt(row.querySelector(".rss-source-priority")?.value || "0", 10);
  const base = {
    id,
    name: row.querySelector(".rss-source-name")?.value.trim() || "",
    url: row.querySelector(".rss-source-url-input")?.value.trim() || "",
    type,
    plugin,
    enabled: original.enabled !== false,
    use_proxy: Boolean(row.querySelector(".rss-source-proxy")?.checked),
    keywords: row.querySelector(".rss-source-keywords")?.value.trim() || "",
    quality: row.querySelector(".rss-source-quality")?.value.trim() || "",
    test_query: row.querySelector(".rss-source-test-query")?.value.trim() || "",
    priority: Number.isFinite(priority) ? priority : 0,
    refresh_interval: Math.max(Number.isFinite(refreshInterval) ? refreshInterval : 30, 5),
    ...(original.last_checked_at ? { last_checked_at: original.last_checked_at } : {}),
  };
  if (plugin !== "haisou") return base;
  const pageSize = Number.parseInt(row.querySelector(".rss-source-page-size")?.value || "20", 10);
  return {
    ...base,
    url: "https://haisou.cc/",
    api_key: row.querySelector(".rss-source-api-key")?.value.trim() || "",
    page_size: Math.max(1, Math.min(Number.isFinite(pageSize) ? pageSize : 20, 100)),
    search_in: row.querySelector(".rss-source-search-in")?.value === "files" ? "files" : "title",
  };
}

function splitFilterText(value) {
  return String(value || "").split(/[,，\n\r]+/).map((item) => item.trim()).filter(Boolean);
}

function addRssSource() {
  const id = `rss_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  const sources = ensureRssSourceIds(rssSourcesValue());
  sources.push({
    id,
    name: "",
    url: "",
    type: "rss",
    plugin: "generic_magnet",
    enabled: true,
    use_proxy: false,
    keywords: "",
    quality: "",
    priority: 0,
    refresh_interval: 30,
    test_query: "",
  });
  state.rssSourceExpanded.add(id);
  state.settings.rss_sources = { value: { ...rssSourcesConfig(), sources } };
  renderSettings();
}

function toggleRssSource(event) {
  const id = event.currentTarget.dataset.toggleRssSource;
  if (state.rssSourceExpanded.has(id)) state.rssSourceExpanded.delete(id);
  else state.rssSourceExpanded.add(id);
  renderSettings();
}

function toggleBuiltinRssSource(event) {
  const id = event.currentTarget.dataset.toggleBuiltinSource;
  if (!id) return;
  const alreadyExpanded = state.builtinRssSourceExpanded.has(id);
  state.builtinRssSourceExpanded.clear();
  if (!alreadyExpanded) state.builtinRssSourceExpanded.add(id);
  renderSettings();
}

function removeRssSource(event) {
  const id = event.currentTarget.dataset.removeRssSource;
  const sources = ensureRssSourceIds(rssSourcesValue()).filter((source) => source.id !== id);
  state.rssSourceExpanded.delete(id);
  state.settings.rss_sources = { value: { ...rssSourcesConfig(), sources } };
  renderSettings();
}
