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
        <div class="emby-library-grid">
          ${libraries.length ? libraries.map((item) => {
            const initial = escapeHtml((item.name || "📁").charAt(0));
            const image = item.image_url
              ? `<img class="library-image" src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.name || "")}" onerror="this.style.visibility='hidden'" />`
              : `<div class="emby-placeholder">${initial}</div>`;
            return `<div class="emby-card emby-library-card">
              ${image}
              <div class="emby-library-meta">
                <h3>${escapeHtml(item.name || "媒体库")}</h3>
                <p>${escapeHtml(item.collection_type || "媒体库")} · ${item.child_count || 0} 部</p>
              </div>
            </div>`;
          }).join("") : `<div class="empty-state"><div class="empty-icon">◌</div><h3>暂无媒体库数据</h3></div>`}
        </div>
      </div>
      <div class="emby-side-section">
        <div class="section-header"><h2>历史记录</h2></div>
        <div class="emby-history-list">
          ${history.length ? history.slice(0, 6).map((item) => {
            const title = escapeHtml(item.name || item.title || "项目");
            const date = item.date_played || "";
            const thumb = item.image_url
              ? `<img src="${escapeHtml(item.image_url)}" alt="" onerror="this.style.display='none'" />`
              : `<div class="emby-history-thumb">🎬</div>`;
            return `<div class="emby-history-item">${thumb}<div><h3>${title}</h3><p>${date ? escapeHtml(date) : "已播放"}</p></div></div>`;
          }).join("") : `<div class="empty-state"><div class="empty-icon">◌</div><h3>暂无观看历史</h3></div>`}
        </div>
        <div class="section-header" style="margin-top:16px"><h2>用户</h2></div>
        <div class="emby-grid">
          ${users.length ? users.slice(0, 3).map((user) => {
            const name = escapeHtml(user.name || user.username || "用户");
            const initial = name.charAt(0).toUpperCase();
            return `<div class="emby-card"><div class="emby-placeholder">${initial}</div><div><div style="font-weight:600;font-size:14px">${name}</div><div style="font-size:12px;color:var(--dim)">管理员</div></div></div>`;
          }).join("") : `<div class="emby-card"><div class="emby-placeholder">A</div><div><div style="font-weight:600;font-size:14px">Admin</div><div style="font-size:12px;color:var(--dim)">管理员</div></div></div>`}
          <div style="display:flex;gap:12px;font-size:12px;color:var(--dim);margin-top:8px;grid-column:1 / -1">
            <span>📺 ${movieCount + seriesCount} 部</span>
            <span>📀 ${data.media_count || 0} 集</span>
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
