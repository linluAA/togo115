async function renderLogs() {
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
    const payload = formatLogPayload(log.payload);
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

function formatLogPayload(raw) {
  if (!raw) return "";
  try {
    const value = JSON.parse(raw);
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return formatLogPayloadObject(value);
    }
    return JSON.stringify(value, null, 2);
  } catch {
    return String(raw);
  }
}

function formatLogPayloadObject(payload) {
  const labelMap = {
    source: "来源",
    plugin: "插件",
    query: "查询",
    status_code: "状态码",
    error_type: "错误类型",
    error: "错误",
    url: "地址",
    final_url: "最终地址",
    count: "数量",
  };
  const priority = ["source", "plugin", "query", "status_code", "error_type", "error", "url", "final_url", "count"];
  const keys = [...priority, ...Object.keys(payload).filter((key) => !priority.includes(key))];
  const lines = [];
  for (const key of keys) {
    if (!(key in payload)) continue;
    const value = formatLogPayloadValue(key, payload[key]);
    if (!value) continue;
    lines.push(`${labelMap[key] || key}：${value}`);
  }
  return lines.join("\n");
}

function formatLogPayloadValue(key, value) {
  if (value === null || value === undefined || value === "") return "";
  if (key === "url" || key === "final_url") return decodeLogUrl(String(value));
  if (key === "error") return compactLogError(String(value));
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value);
}

function decodeLogUrl(value) {
  try {
    const url = new URL(value);
    const query = decodeURIComponent(url.search);
    return `${url.origin}${url.pathname}${query}${url.hash}`;
  } catch {
    try {
      return decodeURIComponent(value);
    } catch {
      return value;
    }
  }
}

function compactLogError(value) {
  const status = value.match(/Server error '(\d{3})/i)?.[1];
  if (status === "503") return "HTTP 503：订阅源临时不可用或触发站点限流";
  if (status === "429") return "HTTP 429：订阅源请求过快，稍后会自动重试";
  return value.replace(/\s*For more information check:.*/is, "").trim();
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



