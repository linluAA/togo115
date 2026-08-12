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
            const image = item.image_url
              ? `<img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.name || "")}" style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-lg)" onerror="this.style.display='none'" />`
              : "";
            return `<div class="media-card">
              <div class="poster">${image}<div class="overlay"><div class="rating">${item.child_count || 0} 部</div></div></div>
              <div class="card-body"><div class="title">${escapeHtml(item.name || "媒体库")}</div><div class="meta"><span>${item.collection_type || "媒体库"}</span></div></div>
            </div>`;
          }).join("") : `<div class="empty-state"><div class="empty-icon">◌</div><h3>暂无媒体库数据</h3></div>`}
        </div>
      </div>
      <div class="emby-side-section">
        <div class="section-header"><h2>历史记录</h2></div>
        <div class="activity-feed" style="background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg);padding:12px 16px">
          ${history.length ? history.slice(0, 6).map((item) => {
            const title = escapeHtml(item.name || item.title || "项目");
            const date = item.date_played || "";
            return `<div class="activity-item">
              <span class="a-dot" style="background:var(--green)"></span>
              <span class="a-text"><strong>${title}</strong> 已播放</span>
              <span class="a-time">${date ? escapeHtml(date) : ""}</span>
            </div>`;
          }).join("") : `<div class="activity-item"><span class="a-text" style="color:var(--dim)">暂无观看历史</span></div>`}
        </div>
        <div class="section-header" style="margin-top:16px"><h2>用户</h2></div>
        <div style="background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg);padding:16px">
          ${users.length ? users.slice(0, 3).map((user) => {
            const name = escapeHtml(user.name || user.username || "用户");
            const initial = name.charAt(0).toUpperCase();
            return `<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
              <div style="width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,var(--amber),var(--coral));display:flex;align-items:center;justify-content:center;font-weight:700;color:#0b1117;flex-shrink:0">${initial}</div>
              <div><div style="font-weight:600;font-size:14px">${name}</div><div style="font-size:12px;color:var(--dim)">管理员</div></div>
            </div>`;
          }).join("") : `<div style="display:flex;align-items:center;gap:12px">
            <div style="width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,var(--amber),var(--coral));display:flex;align-items:center;justify-content:center;font-weight:700;color:#0b1117">A</div>
            <div><div style="font-weight:600;font-size:14px">Admin</div><div style="font-size:12px;color:var(--dim)">管理员</div></div>
          </div>`}
          <div style="display:flex;gap:12px;font-size:12px;color:var(--dim);margin-top:8px">
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
