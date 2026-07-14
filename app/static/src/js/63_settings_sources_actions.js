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
  const vncWindow = openHdhiveNoVncWindow();
  const type = normalizeRssSourceType(row.querySelector(".rss-source-type")?.value || "site_plugin");
  const plugin = normalizeSitePlugin({ plugin: row.querySelector(".rss-source-plugin")?.value || "hdhive", url: row.querySelector(".rss-source-url-input")?.value.trim() || "" });
  const source = {
    ...rssSourceFromRow(row, id, {}, type, plugin),
    enabled: true,
  };
  if (resultBox) {
    resultBox.classList.remove("hidden");
    resultBox.innerHTML = `<span class="muted">正在打开影巢登录浏览器...</span>`;
  }
  try {
    const data = await api("/api/hdhive/login-browser", {
      method: "POST",
      timeoutMs: 12000,
      body: JSON.stringify({ source }),
    });
    navigateHdhiveNoVncWindow(vncWindow, data.novnc_url);
    if (data.ok) {
      const message = data.queued === false ? "影巢登录浏览器已在运行" : "影巢登录浏览器已打开，登录完成后关闭窗口";
      toast(message);
      if (resultBox) resultBox.innerHTML = `<span class="ok-text">${escapeHtml(message)}</span><div class="rss-source-diagnostic"><span>noVNC：${escapeHtml(hdhiveNoVncUrl(data.novnc_url))}</span><span>用户目录：${escapeHtml(data.user_data_dir || "data/hdhive-browser")}</span>${data.warning ? `<span>${escapeHtml(data.warning)}</span>` : ""}</div>`;
    } else {
      const message = data.error || "打开影巢登录浏览器失败";
      toast(message);
      if (resultBox) resultBox.innerHTML = `<span class="warn-text">登录浏览器不可用</span> · ${escapeHtml(message)}<div class="rss-source-diagnostic"><span>noVNC：${escapeHtml(hdhiveNoVncUrl(data.novnc_url))}</span></div>`;
    }
  } catch (error) {
    navigateHdhiveNoVncWindow(vncWindow);
    toast(`打开影巢登录浏览器失败：${error.message}`);
    if (resultBox) resultBox.innerHTML = `<span class="warn-text">登录浏览器不可用</span> · ${escapeHtml(error.message)}<div class="rss-source-diagnostic"><span>noVNC：${escapeHtml(hdhiveNoVncUrl())}</span></div>`;
  }
}

function openHdhiveNoVncWindow() {
  const win = window.open("about:blank", "_blank");
  if (win) {
    win.document.title = "HDHive noVNC";
    win.document.body.innerHTML = "正在打开 noVNC...";
  }
  return win;
}

function navigateHdhiveNoVncWindow(win, url) {
  const target = hdhiveNoVncUrl(url);
  if (win && !win.closed) win.location.href = target;
  else window.open(target, "_blank");
}

function hdhiveNoVncUrl(url) {
  if (url) return url;
  const target = new URL("/novnc/vnc.html", window.location.origin);
  target.searchParams.set("autoconnect", "true");
  target.searchParams.set("resize", "remote");
  target.searchParams.set("path", "api/novnc/websockify");
  return target.toString();
}
