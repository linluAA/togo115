async function renderEmby() {
  const root = $("#view");
  root.innerHTML = `<div class="empty-state"><div class="empty-icon">◌</div><h3>正在读取 Emby 看板...</h3></div>`;
  const data = await api("/api/emby/dashboard");
  if (data.error) {
    root.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠</div><h3>Emby 数据获取失败</h3><p>${escapeHtml(data.error)}</p></div>`;
    return;
  }
  const movieCount = data.movie_count ?? data.counts?.MovieCount ?? 0;
  const seriesCount = data.series_count ?? data.counts?.SeriesCount ?? 0;
  const libraries = data.libraries || [];
  const history = data.history || [];
  const users = data.users || [];
  root.innerHTML = `
    <div class="emby-sections view-section">
      <div class="emby-main-section">
        <div class="section-header">
          <h2>媒体库</h2>
          <button class="btn btn-secondary btn-sm" id="syncEmbyLibrary">同步</button>
        </div>
        <div class="media-grid" style="grid-template-columns:repeat(auto-fill,minmax(140px,1fr));margin-bottom:24px">
          ${libraries.length ? libraries.map((item) => {
            const name = escapeHtml(item.name || "媒体库");
            const count = item.child_count || 0;
            const type = escapeHtml(item.collection_type || "媒体库");
            const image = item.image_url
              ? `<img src="${escapeHtml(item.image_url)}" alt="${name}" style="width:100%;height:100%;object-fit:cover" onerror="this.style.display='none'" />`
              : `<div style="font-size:32px;color:var(--dim)">📁</div>`;
            return `<div class="media-card" title="${name}">
              <div class="poster">${image}</div>
              <div class="card-body">
                <div class="title">${name}</div>
                <div class="meta"><span>${count} 部</span><span class="badge">${type}</span></div>
              </div>
            </div>`;
          }).join("") : `<div class="empty-state" style="grid-column:1/-1"><div class="empty-icon">◌</div><h3>暂无媒体库数据</h3></div>`}
        </div>
      </div>
      <div class="emby-side-section">
        <div class="section-header"><h2>历史记录</h2></div>
        <div class="activity-feed" style="background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg);padding:12px 16px">
          ${history.length ? history.slice(0, 5).map((item) => {
            const title = escapeHtml(item.name || item.title || "项目");
            const date = item.date_played || "已播放";
            const status = item.status === "downloading" ? "var(--amber)" : "var(--green)";
            const statusText = item.status === "downloading" ? "下载中" : "已播放";
            return `<div class="activity-item"><span class="a-dot" style="background:${status}"></span><span class="a-text"><strong>${title}</strong> ${statusText}</span><span class="a-time">${escapeHtml(date)}</span></div>`;
          }).join("") : `<div class="empty-state" style="margin:0;padding:16px 0"><div class="empty-icon">◌</div><h3>暂无观看历史</h3></div>`}
        </div>
        <div class="section-header" style="margin-top:16px"><h2>用户</h2></div>
        <div style="background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg);padding:16px">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
            <div style="width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,var(--amber),var(--coral));display:flex;align-items:center;justify-content:center;font-weight:700;color:#0b1117">${users.length ? escapeHtml((users[0].name || users[0].username || "U").charAt(0).toUpperCase()) : "A"}</div>
            <div><div style="font-weight:600;font-size:14px">${users.length ? escapeHtml(users[0].name || users[0].username || "用户") : "Admin"}</div><div style="font-size:12px;color:var(--dim)">管理员</div></div>
          </div>
          <div style="display:flex;gap:12px;font-size:12px;color:var(--dim)">
            <span>📺 ${movieCount + seriesCount} 部</span>
            <span>📀 ${data.media_count || 0} 集</span>
            <span>💾 ${data.storage_used || "-"}</span>
          </div>
        </div>
      </div>
    </div>
  `;
  $("#syncEmbyLibrary")?.addEventListener("click", async () => {
    try {
      const res = await api("/api/emby/sync", { method: "POST" });
      toast(res.ok ? "媒体库同步已启动" : `同步失败：${res.error || "未知错误"}`);
    } catch (error) {
      toast(`同步失败：${error.message}`);
    }
  });
}
