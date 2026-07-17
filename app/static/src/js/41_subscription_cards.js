function subscriptionCards() {
  if (state.subscriptionStatus === "completed") state.subscriptionStatus = "all";
  const filtered = state.subscriptions.filter((item) => {
    const matchType = state.subscriptionType === "all" || item.media_type === state.subscriptionType;
    const matchStatus = state.subscriptionStatus === "all" || item.status === state.subscriptionStatus;
    return matchType && matchStatus;
  });
  const cards = filtered.map((item) => {
      const embyCount = item.emby_count || 0;
      const tmdbTotal = item.tmdb_total_count || 0;
      const progressPercent = item.media_type === "movie"
        ? (item.in_library ? 100 : 0)
        : (tmdbTotal ? Math.min(100, Math.round((embyCount / tmdbTotal) * 100)) : (item.in_library ? 100 : 0));
      const library = item.media_type === "movie"
        ? (item.in_library ? "已入库" : "未入库")
        : (item.in_library
          ? (tmdbTotal ? `${embyCount}/${tmdbTotal} 集` : `已入库 ${embyCount} 集`)
          : "未入库");
      const poster = item.poster_url || posterUrl({});
      const keywords = (item.keywords || []).join(", ") || "未设置关键词";
      const completed = item.status === "completed" || (item.media_type === "movie"
        ? Boolean(item.in_library)
        : Boolean(tmdbTotal && embyCount >= tmdbTotal));
      const statusText = completed ? "订阅完成" : (item.status === "active" ? "订阅中" : "已暂停");
      const statusClass = completed ? "completed" : (item.status === "active" ? "active" : "paused");
      const checked = state.selectedSubscriptionIds.has(item.id) ? "checked" : "";
      const keywordTags = (item.keywords || []).slice(0, 2).map((keyword) => `<span>${escapeHtml(keyword)}</span>`).join("");
      const health = item.health || {};
      const rules = item.quality_rules || {};
      const ruleTags = [
        ...(rules.preferred_quality || []).slice(0, 1).map((value) => `优先 ${value}`),
        ...(rules.exclude_keywords || []).slice(0, 1).map((value) => `排除 ${value}`),
        rules.accept_mode && rules.accept_mode !== "all" ? (rules.accept_mode === "pack" ? "只要合集" : "只要单集") : "",
      ].filter(Boolean).slice(0, 2).map((value) => `<span>${escapeHtml(value)}</span>`).join("");
      return `<article class="subscription-card ${state.subscriptionCancelMode ? "selecting" : ""}">
        ${state.subscriptionCancelMode ? `<label class="subscription-select"><input type="checkbox" data-select-subscription="${item.id}" ${checked} /><span></span></label>` : ""}
        <div class="subscription-poster">
          <img src="${escapeHtml(poster)}" alt="${escapeHtml(item.title)}" />
          <div class="subscription-progress" title="${escapeHtml(library)}"><span style="width: ${progressPercent}%"></span></div>
        </div>
        <div class="subscription-info">
          <div class="subscription-title-row">
            <h3>${escapeHtml(item.title)}</h3>
            <div class="subscription-status-menu">
              <button type="button" class="subscription-status-chip ${statusClass}" data-status-menu="${item.id}" aria-expanded="false" title="更改订阅状态">
                ${statusText}
                <span class="subscription-status-caret" aria-hidden="true"></span>
              </button>
              <div class="subscription-status-dropdown hidden" data-status-dropdown="${item.id}">
                <button type="button" class="subscription-status-option ${!completed && item.status === "active" ? "is-current" : ""}" data-set-status="${item.id}" data-status="active">订阅中</button>
                <button type="button" class="subscription-status-option ${!completed && item.status === "paused" ? "is-current" : ""}" data-set-status="${item.id}" data-status="paused">已暂停</button>
                <button type="button" class="subscription-status-option is-finish" data-set-status="${item.id}" data-status="completed">已完结</button>
              </div>
            </div>
          </div>
          <div class="subscription-meta-row">
            <span>${escapeHtml(library)}</span>
            <span class="subscription-badge media-type">${item.media_type === "tv" ? "电视剧" : "电影"}</span>
            ${keywordTags ? `<div class="subscription-keywords">${keywordTags}</div>` : ""}
            ${ruleTags ? `<div class="subscription-rules">${ruleTags}</div>` : ""}
          </div>
          <div class="subscription-health ${escapeHtml(health.state || "idle")}">
            <strong>${escapeHtml(health.label || "等待搜索")}</strong>
            <span>${escapeHtml(health.detail || "还没有健康数据")}</span>
          </div>
          <div class="subscription-card-actions">
            <button type="button" class="keyword-chip" data-edit="${item.id}" title="${escapeHtml(keywords)}">关键词</button>
            <button type="button" class="keyword-chip" data-edit-rules="${item.id}">规则</button>
          </div>
        </div>
      </article>`;
    }).join("");
  return `<section class="subscription-panel">
    <div class="subscription-toolbar">
      <div>
        <span class="eyebrow">SUBSCRIPTIONS</span>
        <h1>我的订阅</h1>
        <p>${state.subscriptions.length} 个订阅 · 显示 ${filtered.length} 个</p>
      </div>
      <div class="subscription-controls">
        <div class="subscription-control-grid">
          <select id="subscriptionTypeFilter" class="control-cell" aria-label="订阅类型">
            <option value="all" ${state.subscriptionType === "all" ? "selected" : ""}>全部类型</option>
            <option value="tv" ${state.subscriptionType === "tv" ? "selected" : ""}>电视剧</option>
            <option value="movie" ${state.subscriptionType === "movie" ? "selected" : ""}>电影</option>
          </select>
          <select id="subscriptionStatusFilter" class="control-cell" aria-label="订阅状态">
            <option value="all" ${state.subscriptionStatus === "all" ? "selected" : ""}>全部状态</option>
            <option value="active" ${state.subscriptionStatus === "active" ? "selected" : ""}>订阅中</option>
            <option value="paused" ${state.subscriptionStatus === "paused" ? "selected" : ""}>已暂停</option>
          </select>
          <button type="button" class="secondary compact-tool control-cell" id="subscriptionReset">重置</button>
          <button type="button" class="secondary compact-tool control-cell" id="searchAllSubscriptions">搜索全部</button>
          <button type="button" class="secondary compact-tool control-cell" id="syncEmbySubscriptions">同步媒体库</button>
          <button type="button" class="danger compact-tool control-cell" id="toggleCancelSubscriptions">${state.subscriptionCancelMode ? "退出取消" : "取消订阅"}</button>
          ${state.subscriptionCancelMode ? `<button type="button" class="danger compact-tool control-cell control-cell-span" id="confirmCancelSubscriptions">确定移除</button>` : ""}
        </div>
      </div>
    </div>
    <div class="subscription-results">
      ${filtered.length ? `<div class="subscription-grid">${cards}</div>` : `<div class="empty">当前筛选没有订阅。</div>`}
    </div>
  </section>`;
}

async function editQualityRules(subscription) {
  const rules = subscription.quality_rules || {};
  const preferred = prompt("优先质量，多个用逗号分隔（例如：2160p,1080p）", (rules.preferred_quality || []).join(", "));
  if (preferred === null) return;
  const excludes = prompt("排除词，多个用逗号分隔（例如：TC,枪版,无字幕）", (rules.exclude_keywords || []).join(", "));
  if (excludes === null) return;
  const groups = prompt("压制组偏好/限定，多个用逗号分隔（留空表示不限）", (rules.release_groups || []).join(", "));
  if (groups === null) return;
  const acceptMode = prompt("资源形式：all=全部，pack=只要合集，single=只要单集", rules.accept_mode || "all");
  if (acceptMode === null) return;
  const split = (value) => value.split(/[,，\n\r]+/).map((item) => item.trim()).filter(Boolean);
  const qualityRules = {
    preferred_quality: split(preferred),
    exclude_keywords: split(excludes),
    release_groups: split(groups),
    accept_mode: ["all", "pack", "single"].includes(String(acceptMode).trim().toLowerCase()) ? String(acceptMode).trim().toLowerCase() : "all",
  };
  await api(`/api/subscriptions/${subscription.id}`, { method: "PUT", body: JSON.stringify({ quality_rules: qualityRules }) });
  await refreshSubscriptionData();
  renderSubscriptions();
  toast("质量规则已保存");
}
