const TMDB_HERO_ROTATE_MS = 45000;

function stopTmdbHeroRotation() {
  if (state.tmdbHeroTimer) {
    clearInterval(state.tmdbHeroTimer);
    state.tmdbHeroTimer = null;
  }
}

function tmdbHeroItemKey(item) {
  if (!item) return "";
  const mediaType = item.media_type === "movie" || item.title ? "movie" : "tv";
  return `${mediaType}-${item.id}`;
}

function buildTmdbHeroPool(tv = [], movie = []) {
  const pool = [];
  const seen = new Set();
  for (const item of [...tv, ...movie]) {
    if (!item || !item.id) continue;
    const key = tmdbHeroItemKey(item);
    if (seen.has(key)) continue;
    seen.add(key);
    pool.push(item);
  }
  return pool;
}

function pickRandomTmdbHero(pool, excludeKey = "") {
  if (!pool.length) return null;
  if (pool.length === 1) return pool[0];
  const candidates = excludeKey ? pool.filter((item) => tmdbHeroItemKey(item) !== excludeKey) : pool;
  const source = candidates.length ? candidates : pool;
  return source[Math.floor(Math.random() * source.length)];
}

function applyTmdbHero(featured) {
  const hero = $(".tmdb-hero");
  const heroFeature = $("#heroFeature");
  if (!featured || !hero) return;
  const title = featured.name || featured.title || "热门内容";
  const year = (featured.first_air_date || featured.release_date || "").slice(0, 4) || "新近热门";
  const mediaType = featured.media_type === "movie" || featured.title ? "movie" : "tv";
  const payloadId = `${mediaType}-${featured.id}`;
  state.tmdbHeroFeaturedKey = payloadId;
  state.mediaPayloads.set(payloadId, {
    title,
    media_type: mediaType,
    tmdb_id: featured.id,
    poster_url: posterUrl(featured),
    overview: featured.overview || "",
    release_year: Number.parseInt(year, 10) || null,
    keywords: [title],
  });
}

function rotateTmdbHeroOnce() {
  if (state.view !== "tmdb" || state.tmdbSearchQuery.trim() || state.tmdbMore) {
    stopTmdbHeroRotation();
    return;
  }
  const featured = pickRandomTmdbHero(state.tmdbHeroPool, state.tmdbHeroFeaturedKey);
  if (!featured) return;
  applyTmdbHero(featured);
}

function startTmdbHeroRotation(pool) {
  stopTmdbHeroRotation();
  state.tmdbHeroPool = Array.isArray(pool) ? pool : [];
  if (state.tmdbHeroPool.length <= 1) return;
  state.tmdbHeroTimer = setInterval(rotateTmdbHeroOnce, TMDB_HERO_ROTATE_MS);
}

async function renderTmdb() {
  const root = $("#view");
  if (state.tmdbMore) {
    stopTmdbHeroRotation();
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
      <div class="toolbar view-section">
        <h2 style="font-size:18px;font-weight:700;color:var(--ink)">${sectionTitle(state.tmdbMore.type)}</h2>
        <span style="color:var(--dim);font-size:13px">${items.length} 个条目 · 第 ${page}/${pageCount} 页</span>
        <div class="toolbar-filters">${pager}</div>
        <button class="btn btn-ghost btn-sm" id="backToTmdb">返回</button>
      </div>
      <div class="view-section">${mediaGrid(pageItems, state.tmdbMore.type, { limit: pageSize, more: false })}</div>
      <div class="tmdb-page-footer">${pager}</div>
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
  const typeFilter = state.tmdbTypeFilter || "all";
  root.innerHTML = `
    <div class="toolbar view-section">
      <button class="btn ${typeFilter === "tv" ? "btn-primary" : "btn-secondary"}" data-tmdb-type="tv">剧集</button>
      <button class="btn ${typeFilter === "movie" ? "btn-primary" : "btn-secondary"}" data-tmdb-type="movie">电影</button>
      <button class="btn ${typeFilter === "all" ? "btn-primary" : "btn-ghost"}" data-tmdb-type="all">高分推荐</button>
      <div class="toolbar-filters">
        <div class="topbar-search" style="width:200px">
          <span class="search-icon">⌕</span>
          <input id="tmdbQuery" placeholder="搜索剧集或电影" value="${escapeHtml(state.tmdbSearchQuery)}" style="border:none;background:transparent;color:var(--ink);font-size:13px;outline:none;width:100%" />
        </div>
      </div>
    </div>
    <div id="tmdbSearchResults" class="${isSearching ? "" : "hidden"}">
      <div class="section-header view-section">
        <h2>搜索结果</h2>
      </div>
      <div class="view-section">${isSearching && state.tmdbSearch.length ? mediaGrid(state.tmdbSearch, "tv") : isSearching ? `<div class="empty">正在搜索...</div>` : ``}</div>
    </div>
    <div id="tmdbTrendingContent" class="${isSearching ? "hidden" : ""}">
      <div class="view-section" id="tmdbLoading">
        <div class="tmdb-loading">
          <div class="tmdb-spinner"></div>
          <p>正在读取 TMDB 榜单...</p>
        </div>
      </div>
      <div id="tmdbTrendingBody" class="hidden">
        <div class="section-header view-section">
          <h2>热门剧集</h2>
        </div>
        <div class="view-section" id="tmdbTvGrid"></div>
        <div class="section-header view-section">
          <h2>热门电影</h2>
        </div>
        <div class="view-section" id="tmdbMovieGrid"></div>
      </div>
    </div>
  `;
  root.querySelectorAll("[data-tmdb-type]").forEach((btn) => btn.addEventListener("click", () => {
    state.tmdbTypeFilter = btn.dataset.tmdbType;
    renderTmdb();
  }));
  root.querySelectorAll("[data-more-type]").forEach((btn) => btn.addEventListener("click", () => {
    const type = btn.dataset.moreType;
    const items = type === "tv" ? (state.tmdbTrending?.tv || []) : (state.tmdbTrending?.movie || []);
    if (!items.length) return toast("暂无数据");
    state.tmdbMore = { type, items, page: 1 };
    renderTmdb();
  }));
  const queryInput = $("#tmdbQuery");
  if (queryInput) {
    queryInput.addEventListener("input", () => {
      state.tmdbSearchQuery = queryInput.value;
      if (!queryInput.value.trim()) clearTmdbSearch();
    });
    queryInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") searchTmdb();
    });
  }
  if (isSearching) {
    stopTmdbHeroRotation();
    bindMediaActions($("#tmdbSearchResults"));
    return;
  }
  await renderTmdbTrending(root);
}

async function renderTmdbTrending(root = $("#view")) {
  const tvGrid = root.querySelector("#tmdbTvGrid");
  const movieGrid = root.querySelector("#tmdbMovieGrid");
  const loading = root.querySelector("#tmdbLoading");
  const trendingBody = root.querySelector("#tmdbTrendingBody");
  if (!tvGrid || !movieGrid || state.tmdbSearchQuery.trim()) return;
  try {
    const data = await loadTmdbTrending(20);
    state.tmdbTrending = data;
    if (state.tmdbSearchQuery.trim()) return;
    if (loading) loading.remove();
    if (trendingBody) trendingBody.classList.remove("hidden");
    const tv = data.tv || [];
    const movie = data.movie || [];
    tvGrid.innerHTML = tv.length
      ? mediaGrid(tv, "tv", { limit: 10, more: true })
      : `<div class="empty-state"><div class="empty-icon">◌</div><h3>暂无数据。</h3></div>`;
    movieGrid.innerHTML = movie.length
      ? mediaGrid(movie, "movie", { limit: 10, more: true })
      : `<div class="empty-state"><div class="empty-icon">◌</div><h3>暂无数据。</h3></div>`;
    bindMediaActions(root);
  } catch (error) {
    if (state.tmdbSearchQuery.trim()) return;
    if (loading) loading.remove();
    if (trendingBody) trendingBody.classList.remove("hidden");
    tvGrid.innerHTML = `<div class="empty-state"><div class="empty-icon">◌</div><h3>TMDB 暂不可用。</h3></div>`;
    movieGrid.innerHTML = `<div class="empty-state"><div class="empty-icon">◌</div><h3>TMDB 暂不可用。</h3></div>`;
  }
}
