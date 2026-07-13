async function saveRssSources(event) {
  event.preventDefault();
  const originals = new Map(ensureRssSourceIds(rssSourcesValue()).map((source) => [source.id, source]));
  const builtinOriginals = new Map(builtinRssSourcesValue().map((source) => [source.id, source]));
  const rows = Array.from(event.currentTarget.querySelectorAll(".rss-source-item:not([data-builtin-source-id])"));
  const builtinRows = Array.from(event.currentTarget.querySelectorAll(".rss-source-item[data-builtin-source-id]"));
  const sources = rows
    .map((row) => {
      const id = row.dataset.sourceId || `rss_${Date.now()}_${Math.random().toString(16).slice(2)}`;
      const original = originals.get(id) || {};
      const refreshInterval = Number.parseInt(row.querySelector(".rss-source-interval")?.value || "30", 10);
      const priority = Number.parseInt(row.querySelector(".rss-source-priority")?.value || "0", 10);
      const type = normalizeRssSourceType(row.querySelector(".rss-source-type")?.value || "rss");
      const plugin = normalizeSitePlugin({ plugin: row.querySelector(".rss-source-plugin")?.value || original.plugin || "generic_magnet", url: row.querySelector(".rss-source-url-input")?.value.trim() || "" });
      return {
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
    })
    .filter((source) => source.url);
  const builtin_sources = Object.fromEntries(
    Array.from(builtinOriginals.values()).map((source) => [source.id, builtinRssOverrideFromSource(source)])
  );
  builtinRows.forEach((row) => {
    const id = row.dataset.builtinSourceId;
    const original = builtinOriginals.get(id) || {};
    const refreshInterval = Number.parseInt(row.querySelector(".rss-source-interval")?.value || "30", 10);
    const priority = Number.parseInt(row.querySelector(".rss-source-priority")?.value || "-50", 10);
    builtin_sources[id] = builtinRssOverrideFromSource({
      ...original,
      url: row.querySelector(".rss-source-url-input")?.value.trim() || original.url || "",
      enabled: Boolean(row.querySelector(".rss-source-enabled")?.checked),
      use_proxy: Boolean(row.querySelector(".rss-source-proxy")?.checked),
      keywords: row.querySelector(".rss-source-keywords")?.value.trim() || "",
      quality: row.querySelector(".rss-source-quality")?.value.trim() || "",
      test_query: row.querySelector(".rss-source-test-query")?.value.trim() || "",
      priority: Number.isFinite(priority) ? priority : -50,
      refresh_interval: Math.max(Number.isFinite(refreshInterval) ? refreshInterval : 30, 5),
    });
  });
  await api("/api/settings/rss_sources", { method: "PUT", body: JSON.stringify({ value: { ...rssSourcesConfig(), sources, builtin_sources } }) });
  state.settings = await api("/api/settings");
  state.rssSourceExpanded.clear();
  state.builtinRssSourceExpanded.clear();
  toast("已保存");
  renderSettings();
}

function rssSourceTestQuery(source) {
  return source.test_query || source.name || null;
}

async function testRssSource(event) {
  const id = event.currentTarget.dataset.testRssSource;
  const row = document.querySelector(`.rss-source-item[data-source-id="${CSS.escape(id)}"]`);
  const resultBox = document.querySelector(`[data-rss-test-result="${CSS.escape(id)}"]`);
  if (!row || !resultBox) return;
  const source = {
    id,
    name: row.querySelector(".rss-source-name")?.value.trim() || "",
    url: row.querySelector(".rss-source-url-input")?.value.trim() || "",
    type: normalizeRssSourceType(row.querySelector(".rss-source-type")?.value || "rss"),
    plugin: normalizeSitePlugin({ plugin: row.querySelector(".rss-source-plugin")?.value || "generic_magnet", url: row.querySelector(".rss-source-url-input")?.value.trim() || "" }),
    enabled: true,
    use_proxy: Boolean(row.querySelector(".rss-source-proxy")?.checked),
    keywords: row.querySelector(".rss-source-keywords")?.value.trim() || "",
    quality: row.querySelector(".rss-source-quality")?.value.trim() || "",
    test_query: row.querySelector(".rss-source-test-query")?.value.trim() || "",
    priority: Number.parseInt(row.querySelector(".rss-source-priority")?.value || "0", 10) || 0,
    refresh_interval: Number.parseInt(row.querySelector(".rss-source-interval")?.value || "30", 10) || 30,
  };
  resultBox.classList.remove("hidden");
  resultBox.innerHTML = `<span class="muted">正在测试...</span>`;
  try {
    const data = await api("/api/rss-sources/test", {
      method: "POST",
      body: JSON.stringify({ source, query: rssSourceTestQuery(source) }),
    });
    if (data.ok) {
      const sample = Array.isArray(data.sample) && data.sample.length
        ? `<div class="rss-source-sample">${data.sample.map((item) => `<div class="rss-source-sample-item"><strong>${escapeHtml(item.title || "资源")}</strong><span>${escapeHtml(item.url || "")}</span></div>`).join("")}</div>`
        : "";
      const diagnostic = data.diagnostic || {};
      const diagnostics = diagnostic.message || data.query || data.final_url
        ? `<div class="rss-source-diagnostic">
            ${data.query ? `<span>查询：${escapeHtml(data.query)}</span>` : ""}
            ${data.final_url ? `<span>URL：${escapeHtml(data.final_url)}</span>` : ""}
            ${diagnostic.detail_candidates !== undefined ? `<span>详情候选：${escapeHtml(String(diagnostic.detail_candidates))}</span>` : ""}
            ${diagnostic.message ? `<span>${escapeHtml(diagnostic.message)}</span>` : ""}
          </div>`
        : "";
      resultBox.innerHTML = `<span class="${Number(data.items || 0) ? "ok-text" : "warn-text"}">可用</span> · ${escapeHtml(String(data.items || 0))} 条结果 · ${escapeHtml(String(data.latency_ms || 0))} ms${diagnostics}${sample}`;
    } else {
      resultBox.innerHTML = `<span class="warn-text">不可用</span> · ${escapeHtml(data.error || "请求失败")}`;
    }
  } catch (error) {
    resultBox.innerHTML = `<span class="warn-text">不可用</span> · ${escapeHtml(error.message)}`;
  }
}


