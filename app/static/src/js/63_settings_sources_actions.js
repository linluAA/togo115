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
      const type = normalizeRssSourceType(row.querySelector(".rss-source-type")?.value || "rss");
      const plugin = normalizeSitePlugin({ plugin: row.querySelector(".rss-source-plugin")?.value || original.plugin || "generic_magnet", url: row.querySelector(".rss-source-url-input")?.value.trim() || "" });
      return rssSourceFromRow(row, id, original, type, plugin);
    })
    .filter((source) => source.url);

  const builtin_sources = Object.fromEntries(
    Array.from(builtinOriginals.values()).map((source) => [source.id, builtinRssOverrideFromSource(source)])
  );
  builtinRows.forEach((row) => {
    const id = row.dataset.builtinSourceId;
    const original = builtinOriginals.get(id) || {};
    const plugin = normalizeSitePlugin(original);
    const value = rssSourceFromRow(row, id, original, "site_plugin", plugin);
    builtin_sources[id] = builtinRssOverrideFromSource({
      ...original,
      ...value,
      enabled: Boolean(row.querySelector(".rss-source-enabled")?.checked),
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
  const type = normalizeRssSourceType(row.querySelector(".rss-source-type")?.value || "rss");
  const plugin = normalizeSitePlugin({ plugin: row.querySelector(".rss-source-plugin")?.value || "generic_magnet", url: row.querySelector(".rss-source-url-input")?.value.trim() || "" });
  const source = {
    ...rssSourceFromRow(row, id, {}, type, plugin),
    enabled: true,
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

async function loginHdhiveSource(event) {
  const id = event.currentTarget.dataset.loginHdhiveSource;
  const row = document.querySelector(`.rss-source-item[data-source-id="${CSS.escape(id)}"]`);
  const resultBox = document.querySelector(`[data-rss-test-result="${CSS.escape(id)}"]`);
  if (!row) return;
  const type = normalizeRssSourceType(row.querySelector(".rss-source-type")?.value || "site_plugin");
  const plugin = normalizeSitePlugin({ plugin: row.querySelector(".rss-source-plugin")?.value || "hdhive", url: row.querySelector(".rss-source-url-input")?.value.trim() || "" });
  const source = {
    ...rssSourceFromRow(row, id, {}, type, plugin),
    enabled: true,
  };
  if (resultBox) {
    resultBox.classList.remove("hidden");
    resultBox.innerHTML = `<span class="muted">正在打开影巢内置浏览器...</span>`;
  }
  try {
    const data = await api("/api/hdhive/browser/open", {
      method: "POST",
      timeoutMs: 30000,
      body: JSON.stringify({ source }),
    });
    showHdhiveBrowser(data);
    if (data.ok) {
      const message = "影巢内置浏览器已打开";
      toast(message);
      if (resultBox) resultBox.innerHTML = `<span class="ok-text">${escapeHtml(message)}</span>${renderHdhiveBrowserMeta(data)}`;
    } else {
      const message = data.error || "打开影巢内置浏览器失败";
      toast(message);
      if (resultBox) resultBox.innerHTML = `<span class="warn-text">内置浏览器不可用</span> · ${escapeHtml(message)}`;
    }
  } catch (error) {
    toast(`打开影巢内置浏览器失败：${error.message}`);
    if (resultBox) resultBox.innerHTML = `<span class="warn-text">内置浏览器不可用</span> · ${escapeHtml(error.message)}`;
  }
}

function showHdhiveBrowser(data) {
  state.hdhiveBrowser = data;
  renderHdhiveBrowser();
  startHdhiveBrowserRefresh();
}

function renderHdhiveBrowserMeta(data) {
  const rows = [
    ["状态", data.diagnostic || ""],
    ["代理", data.proxy_enabled ? (data.proxy_server || "已启用") : "未启用"],
    ["浏览器模式", data.headless === false ? "headed" : "headless"],
    ["地址", data.url || ""],
    ["标题", data.title || ""],
    ["用户目录", data.user_data_dir || "data/hdhive-browser"],
    ["页面摘要", data.page_text_excerpt || ""],
  ].filter(([, value]) => value);
  if (!rows.length) return "";
  return `<div class="rss-source-diagnostic">${rows.map(([label, value]) => `<span>${escapeHtml(label)}：${escapeHtml(value)}</span>`).join("")}</div>`;
}

function renderHdhiveBrowserNotice(data) {
  if (!data?.diagnostic && !data?.proxy_enabled && !data?.page_text_excerpt) return "";
  const diagnosticClass = /错误|拦截|为空|失败|风控|拒绝/.test(data?.diagnostic || "") ? " warn" : "";
  const rows = [
    data?.diagnostic ? `<strong>${escapeHtml(data.diagnostic)}</strong>` : "",
    `代理：${data?.proxy_enabled ? escapeHtml(data.proxy_server || "已启用") : "未启用"}`,
    `浏览器模式：${data?.headless === false ? "headed" : "headless"}`,
    data?.page_text_excerpt ? `页面摘要：${escapeHtml(data.page_text_excerpt)}` : "",
  ].filter(Boolean);
  return `<div class="hdhive-browser-notice${diagnosticClass}">${rows.map((row) => `<span>${row}</span>`).join("")}</div>`;
}

function renderHdhiveBrowser() {
  const data = state.hdhiveBrowser;
  let modal = document.querySelector("#hdhiveBrowserModal");
  if (!data || !data.running) {
    if (modal) modal.remove();
    stopHdhiveBrowserRefresh();
    return;
  }
  const html = `
    <div class="hdhive-browser-dialog">
      <header class="hdhive-browser-header">
        <div>
          <strong>HDHive / 影巢</strong>
          <span title="${escapeHtml(data.url || "")}">${escapeHtml(data.title || data.url || "内置浏览器")}</span>
        </div>
        <div class="inline-actions">
          <button type="button" class="secondary" id="hdhiveBrowserRefresh">刷新</button>
          <button type="button" class="secondary danger-lite" id="hdhiveBrowserReset">重置环境</button>
          <button type="button" class="secondary danger-lite" id="hdhiveBrowserClose">关闭</button>
        </div>
      </header>
      <div class="hdhive-browser-nav">
        <input id="hdhiveBrowserUrl" value="${escapeHtml(data.url || "")}" />
        <button type="button" class="secondary" id="hdhiveBrowserGo">前往</button>
      </div>
      ${renderHdhiveBrowserNotice(data)}
      <div class="hdhive-browser-screen" style="aspect-ratio: ${escapeHtml(data.width || 1365)} / ${escapeHtml(data.height || 900)}">
        <img id="hdhiveBrowserImage" src="${escapeHtml(data.screenshot || "")}" alt="HDHive browser" />
      </div>
      <div class="hdhive-browser-inputs">
        <input id="hdhiveBrowserText" placeholder="输入文本后点击发送" />
        <button type="button" id="hdhiveBrowserType">发送文本</button>
        <button type="button" class="secondary" data-hdhive-key="Enter">Enter</button>
        <button type="button" class="secondary" data-hdhive-key="Backspace">Backspace</button>
        <button type="button" class="secondary" data-hdhive-key="Escape">Esc</button>
      </div>
    </div>`;
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "hdhiveBrowserModal";
    modal.className = "modal-backdrop hdhive-browser-modal";
    document.body.appendChild(modal);
  }
  modal.innerHTML = html;
  bindHdhiveBrowserEvents();
}

function bindHdhiveBrowserEvents() {
  $("#hdhiveBrowserImage")?.addEventListener("click", clickHdhiveBrowser);
  $("#hdhiveBrowserRefresh")?.addEventListener("click", refreshHdhiveBrowser);
  $("#hdhiveBrowserReset")?.addEventListener("click", resetHdhiveBrowser);
  $("#hdhiveBrowserClose")?.addEventListener("click", closeHdhiveBrowser);
  $("#hdhiveBrowserGo")?.addEventListener("click", navigateHdhiveBrowser);
  $("#hdhiveBrowserType")?.addEventListener("click", typeHdhiveBrowserText);
  $("#hdhiveBrowserText")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") typeHdhiveBrowserText();
  });
  document.querySelectorAll("[data-hdhive-key]").forEach((button) => button.addEventListener("click", () => pressHdhiveBrowserKey(button.dataset.hdhiveKey)));
}

async function clickHdhiveBrowser(event) {
  const img = event.currentTarget;
  const rect = img.getBoundingClientRect();
  const width = state.hdhiveBrowser?.width || img.naturalWidth || rect.width;
  const height = state.hdhiveBrowser?.height || img.naturalHeight || rect.height;
  const x = ((event.clientX - rect.left) / rect.width) * width;
  const y = ((event.clientY - rect.top) / rect.height) * height;
  const data = await api("/api/hdhive/browser/click", { method: "POST", timeoutMs: 20000, body: JSON.stringify({ x, y }) });
  showHdhiveBrowser(data);
}

async function refreshHdhiveBrowser() {
  const data = await api("/api/hdhive/browser/snapshot", { timeoutMs: 20000 });
  showHdhiveBrowser(data);
}

async function navigateHdhiveBrowser() {
  const url = $("#hdhiveBrowserUrl")?.value || "";
  const data = await api("/api/hdhive/browser/navigate", { method: "POST", timeoutMs: 30000, body: JSON.stringify({ url }) });
  showHdhiveBrowser(data);
}

async function typeHdhiveBrowserText() {
  const input = $("#hdhiveBrowserText");
  const text = input?.value || "";
  if (!text) return;
  const data = await api("/api/hdhive/browser/type", { method: "POST", timeoutMs: 20000, body: JSON.stringify({ text }) });
  if (input) input.value = "";
  showHdhiveBrowser(data);
}

async function pressHdhiveBrowserKey(key) {
  const data = await api("/api/hdhive/browser/key", { method: "POST", timeoutMs: 20000, body: JSON.stringify({ key }) });
  showHdhiveBrowser(data);
}

async function closeHdhiveBrowser() {
  await api("/api/hdhive/browser/close", { method: "POST", timeoutMs: 12000 });
  state.hdhiveBrowser = null;
  renderHdhiveBrowser();
}

async function resetHdhiveBrowser() {
  const data = await api("/api/hdhive/browser/reset", { method: "POST", timeoutMs: 20000, body: JSON.stringify({ source: {} }) });
  toast(data.message || data.error || "影巢浏览器环境已重置");
  state.hdhiveBrowser = null;
  renderHdhiveBrowser();
}

function startHdhiveBrowserRefresh() {
  if (state.hdhiveBrowserTimer) return;
  state.hdhiveBrowserTimer = setInterval(async () => {
    if (!state.hdhiveBrowser?.running) return;
    try {
      const data = await api("/api/hdhive/browser/snapshot", { timeoutMs: 12000 });
      state.hdhiveBrowser = data;
      renderHdhiveBrowser();
    } catch {
      stopHdhiveBrowserRefresh();
    }
  }, 2500);
}

function stopHdhiveBrowserRefresh() {
  if (state.hdhiveBrowserTimer) clearInterval(state.hdhiveBrowserTimer);
  state.hdhiveBrowserTimer = null;
}
