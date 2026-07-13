async function renderEmby() {
  const root = $("#view");
  root.innerHTML = `<div class="empty">正在读取 Emby 看板...</div>`;
  const data = await api("/api/emby/dashboard");
  const movieCount = data.movie_count ?? data.counts?.MovieCount ?? 0;
  const seriesCount = data.series_count ?? data.counts?.SeriesCount ?? 0;
  root.innerHTML = `
    ${data.error ? `<div class="empty">Emby 数据获取失败：${data.error}</div>` : ""}
    <section class="emby-console">
      <aside class="emby-overview-panel">
        <span class="eyebrow">EMBY</span>
        <h1>媒体库看板</h1>
        <p>查看媒体体量、媒体库封面和最近播放记录。</p>
        <div class="stats">
          <div class="stat"><span>媒体总数</span><b>${data.media_count || 0}</b></div>
          <div class="stat"><span>电视剧</span><b>${seriesCount}</b></div>
          <div class="stat"><span>电影</span><b>${movieCount}</b></div>
          <div class="stat"><span>媒体库</span><b>${(data.libraries || []).length}</b></div>
          <div class="stat"><span>用户</span><b>${(data.users || []).length}</b></div>
          <div class="stat"><span>观看记录</span><b>${(data.history || []).length}</b></div>
        </div>
      </aside>
      <div class="emby-content-stack">
        <section class="section emby-library-section"><div class="section-heading"><h3>媒体库</h3><span>${(data.libraries || []).length} 个</span></div>${embyGrid(data.libraries, "暂无媒体库数据", "library")}</section>
        <section class="section emby-history-section"><div class="section-heading"><h3>观看历史</h3><span>${(data.history || []).length} 条</span></div>${embyGrid(data.history, "暂无观看历史", "history")}</section>
        <section class="section emby-user-section"><div class="section-heading"><h3>用户</h3><span>${(data.users || []).length} 个</span></div>${embyGrid(data.users, "暂无用户数据", "user")}</section>
      </div>
    </section>
  `;
}

function simpleList(items, empty) {
  if (!items || !items.length) return `<div class="empty">${empty}</div>`;
  return `<div class="grid">${items.map((item) => `<div class="card"><div class="card-body"><h3>${item.name || item.title || "项目"}</h3><p class="muted">${item.description || ""}</p></div></div>`).join("")}</div>`;
}

function embyGrid(items, empty, kind) {
  if (!items || !items.length) return `<div class="empty">${empty}</div>`;
  if (kind === "history") {
    return `<div class="emby-history-list">${items.slice(0, 20).map((item) => {
      const title = item.name || item.title || "项目";
      const date = item.date_played || item.description || "";
      const image = item.image_url
        ? `<img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(title)}" onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'emby-history-thumb', textContent:'播放'}))" />`
        : `<div class="emby-history-thumb">播放</div>`;
      return `<article class="emby-history-item">
        ${image}
        <div>
          <h3>${escapeHtml(title)}</h3>
          ${date ? `<p>${escapeHtml(date)}</p>` : ""}
        </div>
      </article>`;
    }).join("")}</div>`;
  }
  return `<div class="emby-grid ${kind === "library" ? "emby-library-grid" : ""}">${items.map((item) => {
    const fallback = kind === "user" ? "" : `<div class="emby-placeholder">媒体</div>`;
    const image = kind === "user"
      ? ""
      : (item.image_url ? `<img class="library-image" src="${item.image_url}" alt="${item.name || item.title || "Emby"}" onerror="this.replaceWith(Object.assign(document.createElement('div'), {className:'emby-placeholder', textContent:'媒体'}))" />` : fallback);
    const metaClass = kind === "library" ? "emby-library-meta" : "";
    const description = kind === "library" ? "" : (item.description || item.collection_type || item.date_played || "");
    return `<article class="emby-card ${kind === "library" ? "emby-library-card" : ""}">
      ${image}
      <div class="${metaClass}">
        <h3>${escapeHtml(item.name || item.title || "项目")}</h3>
        ${description ? `<p>${description}</p>` : ""}
      </div>
    </article>`;
  }).join("")}</div>`;
}
