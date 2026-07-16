function failedTaskPanel() {
  const failed = state.failedTasks || [];
  if (!failed.length) return "";
  return `<section class="failed-task-panel">
    <div class="failed-task-heading">
      <div>
        <h3>失败任务队列</h3>
        <p>${failed.length} 条资源投递失败，可以批量重试或在资源列表单独重试。</p>
      </div>
      <button type="button" class="secondary" id="retryFailedTasks">重试全部</button>
    </div>
    <div class="failed-task-list">
      ${failed.slice(0, 12).map((item) => `<article class="failed-task-item">
        <div>
          <strong>${escapeHtml(item.subscription_title || item.title || "资源")}</strong>
          <span>${escapeHtml(item.last_error || "投递失败")} · 已重试 ${escapeHtml(item.retry_count || 0)} 次</span>
        </div>
        <button type="button" class="secondary" data-deliver="${item.id}">重试</button>
      </article>`).join("")}
    </div>
  </section>`;
}

function resourceStatusLabel(status) {
  const value = String(status || "pending").toLowerCase();
  if (value === "delivered") return "\u5df2\u6295\u9012";
  if (value === "failed" || value === "delivery_failed_final") return "\u6295\u9012\u5931\u8d25";
  if (value === "delivery_failed_retryable") return "\u7b49\u5f85\u91cd\u8bd5";
  if (value === "link_invalid") return "\u94fe\u63a5\u5931\u6548";
  if (value === "pending_recheck") return "\u5f85\u590d\u68c0";
  if (value === "matched_not_needed") return "\u65e0\u9700\u6295\u9012";
  if (value === "pending") return "\u5f85\u5904\u7406";
  return status || "\u672a\u77e5";
}

function resourceStatusClass(status) {
  const value = String(status || "pending").toLowerCase();
  if (value === "delivered") return "ok";
  if (value === "failed" || value === "delivery_failed_final" || value === "link_invalid") return "danger";
  if (value === "delivery_failed_retryable" || value === "pending_recheck") return "warning";
  return "idle";
}

function compactSourceName(source) {
  const value = String(source || "未知来源");
  if (value.includes(":")) return value.split(":").slice(1).join(":") || value;
  return value;
}

function resourceSourceParts(source) {
  const value = compactSourceName(source).trim() || "未知来源";
  const telegram = value.match(/^(-?\d{6,})(.+)$/);
  if (telegram) return { id: telegram[1], name: telegram[2].trim() };
  return { id: "", name: value };
}

function resourceSourceHtml(source) {
  const parts = resourceSourceParts(source);
  if (!parts.id) return `<span class="resource-source-name only">${escapeHtml(parts.name)}</span>`;
  return `<span class="resource-source-id">${escapeHtml(parts.id)}</span><span class="resource-source-name">${escapeHtml(parts.name)}</span>`;
}

function resourceTable() {
  if (!state.resources.length) return `<div class="empty">还没有发现资源链接。</div>`;
  const visibleResources = state.resources.slice(0, state.resourcesLimit);
  return `<div class="resource-panel">
    <div class="resource-toolbar">
      <div>
        <strong>共 ${state.resources.length} 条</strong>
        ${state.resourceDeleteMode ? `<span>已选 ${state.selectedResourceIds.size} 条</span>` : ""}
      </div>
      <div class="resource-toolbar-actions">
        <button type="button" class="secondary compact-tool" id="toggleResourceDelete">${state.resourceDeleteMode ? "取消" : "删除"}</button>
        ${state.resourceDeleteMode ? `<button type="button" class="danger compact-tool" id="confirmResourceDelete">删除选中</button>` : ""}
        <button type="button" class="danger compact-tool" id="clearResources">清空</button>
      </div>
    </div>
    <div class="resource-list ${state.resourceDeleteMode ? "selecting" : ""}">
      ${visibleResources.map((item) => {
        const title = item.display_title || item.subscription_title || item.title || "资源";
        const groupCount = Number(item.group_count || 1);
        const status = resourceStatusLabel(item.status);
        const statusClass = resourceStatusClass(item.status);
        const url = String(item.url || "");
        const checked = state.selectedResourceIds.has(Number(item.id)) ? "checked" : "";
        return `<details class="resource-item">
          <summary>
            ${state.resourceDeleteMode ? `<label class="resource-select" onclick="event.stopPropagation()"><input type="checkbox" data-select-resource="${item.id}" ${checked} /><span></span></label>` : ""}
            <span class="resource-source">${resourceSourceHtml(item.source)}</span>
            <strong>${escapeHtml(title)}</strong>${groupCount > 1 ? `<span class="resource-group-count">${groupCount}</span>` : ""}
            <span class="resource-status ${statusClass}">${escapeHtml(status)}</span>
          </summary>
          <div class="resource-details">
            <div><span>链接</span><a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(url || "空链接")}</a></div>
            <div><span>来源</span><p>${escapeHtml(item.source || "未知来源")}</p></div>
            ${item.message_id ? `<div><span>消息</span><p>${escapeHtml(item.message_id)}</p></div>` : ""}
            <div><span>状态</span><p>${escapeHtml(status)}</p></div>
            <div class="resource-actions"><button class="secondary" data-deliver="${item.id}">重新投递</button></div>
          </div>
        </details>`;
      }).join("")}
    </div>
    ${state.resources.length > visibleResources.length ? `<button class="secondary resource-more" id="loadMoreResources">查看更多资源</button>` : ""}
  </div>`;
}
