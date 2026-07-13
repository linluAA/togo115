async function loadTmdbTrending(limit = 20) {
  const normalizedLimit = Math.max(1, Math.min(Number.parseInt(limit, 10) || 20, 300));
  if (state.tmdbTrending && state.tmdbTrendingLimit >= normalizedLimit) return state.tmdbTrending;
  const data = await api(`/api/tmdb/trending?limit=${normalizedLimit}`);
  state.tmdbTrending = data;
  state.tmdbTrendingLimit = normalizedLimit;
  return data;
}

function rankList(items) {
  if (!items.length) return `<div class="empty">暂无排行数据。</div>`;
  return `<div class="rank-list">${items.map((item, index) => {
    const title = item.name || item.title || "未命名";
    const year = (item.first_air_date || item.release_date || "").slice(0, 4) || "未知";
    const type = item.media_type === "movie" || item.title ? "电影" : "剧集";
    return `<button type="button" class="rank-item" data-detail="${type === "电影" ? `movie-${item.id}` : `tv-${item.id}`}">
      <span>${String(index + 1).padStart(2, "0")}</span>
      <img src="${posterUrl(item)}" alt="${escapeHtml(title)}" />
      <strong>${escapeHtml(title)}</strong>
      <small>${type} · ${year}</small>
    </button>`;
  }).join("")}</div>`;
}

function clearTmdbSearch() {
  state.tmdbSearchQuery = "";
  state.tmdbSearch = [];
  const section = $("#searchSection");
  if (section) {
    section.innerHTML = "";
    section.classList.add("hidden");
  }
  renderTmdbTrending();
}

function mediaGrid(items, type, options = {}) {
  if (!items.length) return `<div class="empty">暂无数据。</div>`;
  const limit = options.limit || 20;
  const visibleItems = items.slice(0, limit);
  const cards = visibleItems.map((item) => {
    const title = item.name || item.title || "未命名";
    const mediaType = item.media_type === "movie" || item.media_type === "tv" ? item.media_type : type;
    const releaseYear = Number.parseInt((item.first_air_date || item.release_date || "").slice(0, 4), 10) || null;
    const payloadId = `${mediaType}-${item.id}`;
    const payload = {
      title,
      media_type: mediaType,
      tmdb_id: item.id,
      poster_url: posterUrl(item),
      overview: item.overview || "",
      release_year: releaseYear,
      keywords: [title],
    };
    state.mediaPayloads.set(payloadId, payload);
    const year = (item.first_air_date || item.release_date || "").slice(0, 4) || "未知";
    return `<article class="media-card">
      <button class="poster-button" data-detail="${payloadId}" aria-label="查看 ${title} 详情">
        <img class="poster" src="${posterUrl(item)}" alt="${escapeHtml(title)}" />
        <span class="poster-overlay">
          <span>详情</span>
        </span>
      </button>
      <div class="media-meta">
        <h3>${escapeHtml(title)}</h3>
        <p><span>${mediaType === "tv" ? "剧集" : "电影"}</span><span>${year}</span></p>
      </div>
    </article>`;
  }).join("");
  const more = options.more ? `<button class="more-card" data-more="${type}" aria-label="查看更多"><span class="arrow">→</span><span class="more-text">查看更多</span></button>` : "";
  return `<div class="media-grid">${cards}${more}</div>`;
}

function bindMediaActions(root = document) {
  root.querySelectorAll("[data-detail]").forEach((btn) => btn.addEventListener("click", () => showMediaDetail(btn.dataset.detail)));
  root.querySelectorAll("[data-more]").forEach((btn) => btn.addEventListener("click", async () => {
    const type = btn.dataset.more;
    btn.disabled = true;
    const originalText = btn.querySelector(".more-text")?.textContent || "查看更多";
    if (btn.querySelector(".more-text")) btn.querySelector(".more-text").textContent = "加载中";
    try {
      const data = await loadTmdbTrending(300);
      state.tmdbMore = { type, items: data[type] || [], page: 1 };
      renderTmdb();
    } catch (error) {
      toast(`榜单加载失败：${error.message}`);
      btn.disabled = false;
      if (btn.querySelector(".more-text")) btn.querySelector(".more-text").textContent = originalText;
    }
  }));
}

async function subscribeMedia(item) {
  if (!item) return;
  const payload = { ...item };
  const subscription = await api("/api/subscriptions", { method: "POST", body: JSON.stringify(payload) });
  upsertSubscription(subscription);
  toast("已加入订阅，后台将自动补全详情并搜索历史消息");
  return subscription;
}

function upsertSubscription(subscription) {
  if (!subscription?.id) return;
  const index = state.subscriptions.findIndex((item) => Number(item.id) === Number(subscription.id));
  if (index >= 0) state.subscriptions[index] = subscription;
  else state.subscriptions = [subscription, ...state.subscriptions];
}

async function searchTmdb() {
  const query = $("#tmdbQuery").value.trim();
  if (!query) {
    clearTmdbSearch();
    return;
  }
  state.tmdbSearchQuery = query;
  const section = $("#searchSection");
  const trending = $("#trendingSection");
  if (trending) trending.classList.add("hidden");
  section.classList.remove("hidden");
  section.innerHTML = `<div class="empty">正在搜索...</div>`;
  const data = await api(`/api/tmdb/search?q=${encodeURIComponent(query)}`);
  if (!section.isConnected || state.tmdbSearchQuery !== query) return;
  state.tmdbSearch = data.results || [];
  section.innerHTML = `<h3>搜索结果</h3>${state.tmdbSearch.length ? mediaGrid(state.tmdbSearch, "tv") : `<div class="empty">没有搜索到相关结果。</div>`}`;
  bindMediaActions(section);
}
