async function renderTmdb() {
  const root = $("#view");
  if (state.tmdbMore) {
    const items = state.tmdbMore.items || [];
    const pageSize = tmdbMorePageSize();
    const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
    const page = Math.min(Math.max(Number.parseInt(state.tmdbMore.page, 10) || 1, 1), pageCount);
    const start = (page - 1) * pageSize;
    const pageItems = items.slice(start, start + pageSize);
    const rangeStart = items.length ? start + 1 : 0;
    const rangeEnd = Math.min(start + pageSize, items.length);
    const pager = `<div class="tmdb-page-actions">
      <button class="secondary" data-tmdb-page="prev" ${page <= 1 ? "disabled" : ""}>上一页</button>
      <span>${rangeStart}-${rangeEnd}</span>
      <button class="secondary" data-tmdb-page="next" ${page >= pageCount ? "disabled" : ""}>下一页</button>
    </div>`;
    state.tmdbMore.page = page;
    root.innerHTML = `
      <section class="page-heading compact-toolbar tmdb-more-heading">
        <div><h1>${sectionTitle(state.tmdbMore.type)}</h1><p>${items.length} 个条目 · 第 ${page}/${pageCount} 页</p></div>
        ${pager}
        <button class="secondary" id="backToTmdb">返回</button>
      </section>
      <section class="section media-section tmdb-more-section">${mediaGrid(pageItems, state.tmdbMore.type, { limit: pageSize, more: false })}</section>
      <section class="tmdb-page-footer">${pager}</section>
    `;
    $("#backToTmdb").addEventListener("click", () => {
      state.tmdbMore = null;
      renderTmdb();
    });
    document.querySelectorAll("[data-tmdb-page]").forEach((btn) => btn.addEventListener("click", () => {
      if (!state.tmdbMore) return;
      const direction = btn.dataset.tmdbPage;
      const current = Number.parseInt(state.tmdbMore.page, 10) || 1;
      state.tmdbMore.page = direction === "next" ? Math.min(current + 1, pageCount) : Math.max(current - 1, 1);
      window.scrollTo({ top: 0, behavior: "smooth" });
      renderTmdb();
    }));
    bindMediaActions(root);
    return;
  }
  const isSearching = Boolean(state.tmdbSearchQuery.trim());
  const activeSubscriptions = state.subscriptions.filter((item) => item.status === "active").length;
  const completedSubscriptions = state.subscriptions.filter((item) => item.status === "completed" || item.in_library).length;
  const discoveredResources = state.resources.length;
  root.innerHTML = `
    <section class="tmdb-hero">
      <div class="tmdb-hero-copy">
        <span class="eyebrow">TMDB</span>
        <h1>发现影视资源</h1>
        <p>从榜单、搜索和订阅源里集中管理追新资源。</p>
        <div class="hero-metrics">
          <span><b>${activeSubscriptions}</b>订阅中</span>
          <span><b>${completedSubscriptions}</b>已入库</span>
          <span><b>${discoveredResources}</b>发现资源</span>
        </div>
      </div>
      <div class="tmdb-hero-panel">
        <div class="hero-feature" id="heroFeature">
          <div class="hero-feature-copy">
            <span>正在读取榜单</span>
            <strong>TMDB Trending</strong>
            <small>热门内容同步中</small>
          </div>
        </div>
        <div class="hero-quick-grid">
          <span><b>剧集</b><small>热门榜</small></span>
          <span><b>电影</b><small>新近热门</small></span>
          <span><b>订阅</b><small>自动追新</small></span>
        </div>
        <div class="tmdb-search">
          <input id="tmdbQuery" placeholder="搜索剧集或电影" value="${escapeHtml(state.tmdbSearchQuery)}" />
          <button id="tmdbSearchBtn">搜索</button>
        </div>
      </div>
    </section>
    <section class="section media-section ${isSearching ? "" : "hidden"}" id="searchSection">
      ${isSearching ? `<h3>搜索结果</h3>${state.tmdbSearch.length ? mediaGrid(state.tmdbSearch, "tv") : `<div class="empty">没有搜索到相关结果。</div>`}` : ""}
    </section>
    <section class="section media-section ${isSearching ? "hidden" : ""}" id="trendingSection"><div class="empty">正在读取 TMDB 榜单...</div></section>
  `;
  $("#tmdbSearchBtn").addEventListener("click", () => searchTmdb());
  const queryInput = $("#tmdbQuery");
  queryInput.addEventListener("input", () => {
    state.tmdbSearchQuery = queryInput.value;
    if (!queryInput.value.trim()) clearTmdbSearch();
  });
  queryInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") searchTmdb();
  });
  if (isSearching) {
    bindMediaActions($("#searchSection"));
    return;
  }
  await renderTmdbTrending(root);
}

async function renderTmdbTrending(root = $("#view")) {
  const section = $("#trendingSection");
  if (!section || state.tmdbSearchQuery.trim()) return;
  section.classList.remove("hidden");
  if (!state.tmdbTrending) section.innerHTML = `<div class="empty">正在读取 TMDB 榜单...</div>`;
  try {
    const data = await loadTmdbTrending(20);
    state.tmdbTrending = data;
    if (!section.isConnected || state.tmdbSearchQuery.trim()) return;
    const tv = data.tv || [];
    const movie = data.movie || [];
    const featured = tv[0] || movie[0];
    const hero = $(".tmdb-hero");
    const heroFeature = $("#heroFeature");
    if (featured && hero) {
      const title = featured.name || featured.title || "热门内容";
      const year = (featured.first_air_date || featured.release_date || "").slice(0, 4) || "新近热门";
      const mediaType = featured.media_type === "movie" || featured.title ? "movie" : "tv";
      const payloadId = `${mediaType}-${featured.id}`;
      state.mediaPayloads.set(payloadId, {
        title,
        media_type: mediaType,
        tmdb_id: featured.id,
        poster_url: posterUrl(featured),
        overview: featured.overview || "",
        release_year: Number.parseInt(year, 10) || null,
        keywords: [title],
      });
      const heroOverlay = state.theme === "light"
        ? "linear-gradient(90deg, rgba(248, 251, 252, .96), rgba(248, 251, 252, .76), rgba(248, 251, 252, .38))"
        : "linear-gradient(90deg, rgba(9, 15, 17, .94), rgba(9, 15, 17, .62), rgba(9, 15, 17, .28))";
      hero.style.backgroundImage = `${heroOverlay}, url('${backdropUrl(featured)}')`;
      if (heroFeature) {
        heroFeature.innerHTML = `
          <img class="hero-feature-poster" src="${posterUrl(featured)}" alt="${escapeHtml(title)}" />
          <div class="hero-feature-copy">
            <span>今日看点</span>
            <strong>${escapeHtml(title)}</strong>
            <small>${year} · ${mediaType === "movie" ? "电影" : "剧集"}</small>
          </div>
          <button type="button" class="hero-feature-link" data-detail="${payloadId}">查看</button>
        `;
      }
    }
    section.innerHTML = `
      <div class="tmdb-board">
        <section class="section media-section tmdb-board-main">
          <div class="section-heading"><h3>热门剧集</h3><span>${tv.length} 个</span></div>
          ${mediaGrid(tv, "tv", { limit: 9, more: true })}
        </section>
        <aside class="section tmdb-rank-panel">
          <div class="section-heading"><h3>榜单快览</h3><span>Top 18</span></div>
          ${rankList([...tv.slice(0, 9), ...movie.slice(0, 9)])}
        </aside>
        <section class="section media-section tmdb-board-wide">
          <div class="section-heading"><h3>热门电影</h3><span>${movie.length} 个</span></div>
          ${mediaGrid(movie, "movie", { limit: 9, more: true })}
        </section>
      </div>
    `;
    bindMediaActions(root);
  } catch (error) {
    if (!section.isConnected || state.tmdbSearchQuery.trim()) return;
    section.innerHTML = `<div class="empty">TMDB 暂不可用。</div>`;
  }
}
