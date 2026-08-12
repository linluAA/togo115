function subscriptionCards(filtered) {
  const subs = filtered || state.subscriptions;
  if (!subs.length) return `<div class="empty-state view-section"><div class="empty-icon">◌</div><h3>当前筛选没有订阅</h3></div>`;
  const cards = subs.map((item) => {
    const embyCount = item.emby_count || 0;
    const tmdbTotal = item.tmdb_total_count || 0;
    const progressPercent = item.media_type === "movie"
      ? (item.in_library ? 100 : 0)
      : (tmdbTotal ? Math.min(100, Math.round((embyCount / tmdbTotal) * 100)) : (item.in_library ? 100 : 0));
    const completed = item.status === "completed" || (item.media_type === "movie"
      ? Boolean(item.in_library)
      : Boolean(tmdbTotal && embyCount >= tmdbTotal));
    const statusText = completed ? "已完成" : (item.status === "active" ? "活跃" : "暂停");
    const statusClass = completed ? "status-completed" : (item.status === "active" ? "status-active" : "status-paused");
    const libraryText = item.media_type === "movie"
      ? (item.in_library ? "已入库" : "未入库")
      : (tmdbTotal ? `${embyCount}/${tmdbTotal} 集` : (item.in_library ? "已入库" : "未入库"));
    const footerStatus = completed ? "已完结" : (item.status === "active" ? "搜索中" : "已暂停");
    const footerColor = completed ? "var(--green)" : (item.status === "active" ? "var(--amber)" : "var(--rose)");
    return `<div class="sub-card" data-sub-id="${item.id}">
      <div class="sub-card-header">
        <div class="poster-sm">${posterImgTag(item, item.title)}</div>
        <div class="info">
          <div class="title">${escapeHtml(item.title)}</div>
          <div class="desc">
            <span class="tag">${item.media_type === "tv" ? "剧集" : "电影"}</span>
            ${item.year ? `<span class="tag">${escapeHtml(String(item.year))}</span>` : ""}
          </div>
        </div>
        <span class="status-badge ${statusClass}">${statusText}</span>
      </div>
      <div class="sub-card-progress"><div class="bar" style="width:${progressPercent}%"></div></div>
      <div class="sub-card-footer">
        <span class="chip">TG 自动搜索</span>
        <span class="chip">${libraryText}</span>
        <span style="margin-left:auto;color:${footerColor}">${footerStatus}</span>
      </div>
    </div>`;
  }).join("");
  return `<div class="sub-grid view-section">${cards}</div>`;
}
