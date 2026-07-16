async function renderLogs() {
  const metrics = await loadSearchMetrics();

  const root = $("#view");
  state.logs = [];
  state.logsHasMore = false;
  root.innerHTML = `
    <section class="page-heading log-heading">
      <div><span class="eyebrow">EVENTS</span><h1>运行日志</h1></div>
    </section>
    <section class="log-toolbar">
      <span class="log-status">● 已连接</span>
      <input id="logFilter" placeholder="输入过滤关键字" />
      <button class="${state.logsMode === "simple" ? "active" : ""}" data-mode="simple">重要</button>
      <button class="${state.logsMode === "debug" ? "active" : ""}" data-mode="debug">全部</button>
      <button class="danger" id="clearLogView">清空</button>
    </section>
    ${renderSearchMetrics(metrics)}
    <div class="log-terminal"><div class="log-list"><div class="empty">正在读取日志...</div></div></div>
    <button class="secondary log-more" id="loadMoreLogs">加载更多</button>
  `;
  root.querySelectorAll("[data-mode]").forEach((btn) => btn.addEventListener("click", () => {
    state.logsMode = btn.dataset.mode;
    renderLogs();
  }));
  await loadLogsPage();
  $("#logFilter").addEventListener("input", () => renderLogRows(state.logs));
  $("#clearLogView").addEventListener("click", () => {
    state.logs = [];
    root.querySelector(".log-list").innerHTML = "";
  });
  $("#loadMoreLogs")?.addEventListener("click", () => loadLogsPage());
}

async function loadLogsPage() {
  const button = $("#loadMoreLogs");
  if (button) {
    button.disabled = true;
    button.textContent = "加载中...";
  }
  const beforeId = state.logs.length ? Math.min(...state.logs.map((log) => Number(log.id))) : 0;
  const url = `/api/logs?mode=${state.logsMode}&limit=100${beforeId ? `&before_id=${beforeId}` : ""}`;
  const logs = await api(url);
  const seen = new Set(state.logs.map((log) => Number(log.id)));
  state.logs = [...state.logs, ...logs.filter((log) => !seen.has(Number(log.id)))];
  state.logsHasMore = logs.length >= 100;
  renderLogRows(state.logs);
  if (button) {
    button.disabled = false;
    button.textContent = state.logsHasMore ? "加载更多" : "没有更多日志";
    button.classList.toggle("hidden", !state.logsHasMore && state.logs.length > 0);
  }
}

function renderLogRows(logs) {
  const keyword = $("#logFilter")?.value.trim().toLowerCase() || "";
  const filtered = keyword ? logs.filter((log) => `${log.level} ${log.scope} ${log.message} ${log.payload || ""}`.toLowerCase().includes(keyword)) : logs;
  const grouped = groupLogRows(filtered);
  $(".log-list").innerHTML = grouped.length ? grouped.map((entry, index) => {
    const log = entry.log;
    const time = new Date(log.created_at).toLocaleString();
    let payload = "";
    if (log.payload) {
      try {
        payload = JSON.stringify(JSON.parse(log.payload), null, 2);
      } catch {
        payload = log.payload;
      }
    }
    const repeat = entry.count > 1 ? `<span class="repeat-badge">×${entry.count}</span>` : "";
    return `<details class="log-line ${log.level}">
      <summary>
        <span class="line-no">${index + 1}</span>
        <span class="level">${log.level.toUpperCase()}</span>
        <span class="time">${time}</span>
        <span class="scope">${escapeHtml(log.scope)}</span>
        <span class="message">${escapeHtml(log.message)}${repeat}</span>
      </summary>
      ${payload ? `<pre class="log-payload">${escapeHtml(payload)}</pre>` : ""}
    </details>`;
  }).join("") : `<div class="log-empty">暂无日志</div>`;
}

function groupLogRows(logs) {
  const groups = [];
  for (const log of logs) {
    const previous = groups[groups.length - 1];
    const key = `${log.level}|${log.scope}|${log.message}`;
    if (previous?.key === key) {
      previous.count += 1;
      continue;
    }
    groups.push({ key, log, count: 1 });
  }
  return groups;
}


async function loadSearchMetrics() {
  try {
    return await api("/api/metrics/search");
  } catch (error) {
    console.warn("load search metrics failed", error);
    return null;
  }
}

function renderSearchMetrics(metrics) {
  if (!metrics) {
    return `<section class="search-metrics is-empty"><div class="empty">暂无搜索指标</div></section>`;
  }
  const tg = metrics.telegram || {};
  const share = metrics.share_115 || {};
  const cache = metrics.cache || {};
  const gate = metrics.gate || {};
  const attach = metrics.attach || {};
  const msgCache = cache.message_extract || {};
  const pageCache = cache.external_page || {};
  const desired = metrics.desired_concurrency || metrics.semaphore_limit || 0;
  const cacheHits = (msgCache.hits || 0) + (pageCache.hits || 0);
  const attachParts = [
    attach.created || 0,
    attach.duplicates || 0,
    attach.expired || 0,
    attach.save_failed || 0,
    attach.mismatch || 0,
  ].join('/');
  return `
    <section class="search-metrics" aria-label="搜索性能指标">
      <div class="metric-chip"><span class="metric-label">TG</span><span class="metric-value">${tg.searches || 0}</span></div>
      <div class="metric-chip"><span class="metric-label">R/S/E</span><span class="metric-value">${tg.avg_resolve_ms || 0}/${tg.avg_search_ms || 0}/${tg.avg_extract_ms || 0}<em>ms</em></span></div>
      <div class="metric-chip"><span class="metric-label">p50/p95</span><span class="metric-value">${tg.p50_total_ms || 0}/${tg.p95_total_ms || 0}<em>ms</em></span></div>
      <div class="metric-chip"><span class="metric-label">索引/远程</span><span class="metric-value">${tg.index_hits || 0}/${tg.remote_hits || 0}</span></div>
      <div class="metric-chip"><span class="metric-label">115</span><span class="metric-value">${share.avg_ms || 0}/${share.p95_ms || 0}<em>ms</em></span></div>
      <div class="metric-chip"><span class="metric-label">失效</span><span class="metric-value">${share.expired || 0}/${share.recheck || 0}</span></div>
      <div class="metric-chip metric-chip-wide"><span class="metric-label">Attach</span><span class="metric-value">${attachParts}</span></div>
      <div class="metric-chip"><span class="metric-label">缓存</span><span class="metric-value">${cacheHits}</span></div>
      <div class="metric-chip"><span class="metric-label">Flood</span><span class="metric-value">${gate.flood_events || 0}</span></div>
      <div class="metric-chip"><span class="metric-label">并发</span><span class="metric-value">${metrics.concurrency || 0}/${desired}</span></div>
    </section>
  `;
}
