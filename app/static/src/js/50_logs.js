async function renderLogs() {
  const root = $("#view");
  state.logs = [];
  state.logsHasMore = false;
  state.logsLevel = state.logsLevel || "all";
  root.innerHTML = `
    <div class="log-view-wrap">
    <div class="toolbar view-section">
      <button class="btn ${state.logsLevel === "all" ? "btn-secondary" : "btn-ghost"} btn-sm" data-log-level="all">全部</button>
      <button class="btn ${state.logsLevel === "info" ? "btn-secondary" : "btn-ghost"} btn-sm" data-log-level="info">信息</button>
      <button class="btn ${state.logsLevel === "warn" ? "btn-secondary" : "btn-ghost"} btn-sm" data-log-level="warn">警告</button>
      <button class="btn ${state.logsLevel === "error" ? "btn-secondary" : "btn-ghost"} btn-sm" data-log-level="error">错误</button>
      <div class="toolbar-filters">
        <button class="btn btn-ghost btn-sm" id="clearLogView">清空筛选</button>
      </div>
    </div>
    <div class="log-list view-section" id="logList"><div class="empty-state"><div class="empty-icon">◌</div><h3>正在读取日志...</h3></div></div>
    <div style="text-align:center;padding:16px" id="logMoreWrap">
      <button class="btn btn-ghost btn-sm" id="loadMoreLogs" style="display:none">加载更多</button>
    </div>
    </div>
  `;
  root.querySelectorAll("[data-log-level]").forEach((btn) => btn.addEventListener("click", () => {
    state.logsLevel = btn.dataset.logLevel;
    renderLogs();
  }));
  await loadLogsPage();
  $("#clearLogView").addEventListener("click", () => {
    state.logs = [];
    document.querySelector("#logList").innerHTML = "";
  });
}

async function loadLogsPage() {
  const button = $("#loadMoreLogs");
  if (button) {
    button.disabled = true;
    button.textContent = "加载中...";
  }
  const beforeId = state.logs.length ? Math.min(...state.logs.map((log) => Number(log.id))) : 0;
  const url = `/api/logs?limit=100${beforeId ? `&before_id=${beforeId}` : ""}`;
  const logs = await api(url);
  const seen = new Set(state.logs.map((log) => Number(log.id)));
  state.logs = [...state.logs, ...logs.filter((log) => !seen.has(Number(log.id)))];
  if (state.logs.length > 1000) state.logs = state.logs.slice(0, 1000);
  state.logsHasMore = logs.length >= 100;
  renderLogRows(state.logs);
  if (button) {
    button.disabled = false;
    button.textContent = state.logsHasMore ? "加载更多" : "没有更多日志";
    button.classList.toggle("hidden", !state.logsHasMore && state.logs.length > 0);
    const wrap = $("#logMoreWrap");
    if (wrap) wrap.style.display = state.logsHasMore ? "" : "none";
  }
}

function renderLogRows(logs) {
  const level = state.logsLevel || "all";
  const filtered = level === "all" ? logs : logs.filter((log) => log.level === level);
  const grouped = groupLogRows(filtered);
  const logList = $(".log-list");
  if (!logList) return;
  logList.innerHTML = grouped.length ? grouped.map((entry) => {
    const log = entry.log;
    const time = new Date(log.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const repeat = entry.count > 1 ? ` <span class="repeat-badge">×${entry.count}</span>` : "";
    const payloadHtml = log.payload ? `<div class="log-payload">${escapeHtml(formatLogPayload(log.payload))}</div>` : "";
    return `<details class="log-entry">
      <summary>
        <span class="log-level ${log.level}">${log.level.toUpperCase()}</span>
        <span class="log-time">${time}</span>
        <span class="log-msg">${escapeHtml(log.message)}${repeat}</span>
      </summary>
      ${payloadHtml}
    </details>`;
  }).join("") : `<div class="empty-state"><div class="empty-icon">◌</div><h3>暂无日志</h3></div>`;
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
  const status = value.match(/Server error '(\d{3})'/i)?.[1];
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
