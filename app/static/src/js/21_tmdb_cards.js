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
  if (state.view === "tmdb") renderTmdb();
}

function mediaGrid(items, type, options = {}) {
  if (!items.length) return `<div class="empty">暂无数据。</div>`;
  const limit = options.limit || 20;
  const visibleItems = items.slice(0, limit);
  const cardHtmlList = visibleItems.map((item, index) => {
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
    const rating = item.vote_average ? `★ ${Number(item.vote_average).toFixed(1)}` : "";
    return `<article class="media-card">
      <div class="poster" data-detail="${payloadId}" aria-label="查看 ${title} 详情" title="查看详情">
        <img src="${posterUrl(item)}" alt="${escapeHtml(title)}" loading="lazy" />
        <div class="overlay">
          ${rating ? `<div class="rating">${rating}</div>` : ""}
          <div class="year">${year}</div>
        </div>
      </div>
      <div class="card-body">
        <div class="title">${escapeHtml(title)}</div>
        <div class="meta"><span>${mediaType === "tv" ? "剧集" : "电影"} · ${year}</span></div>
      </div>
    </article>`;
  });
  let html = '<div class="media-grid">';
  html += cardHtmlList.join("");
  html += '</div>';
  return html;
}

function bindMediaActions(root = document) {
  root.querySelectorAll("[data-detail]").forEach((btn) => btn.addEventListener("click", () => showMediaDetail(btn.dataset.detail)));
  root.querySelectorAll("[data-more]").forEach((btn) => btn.addEventListener("click", async () => {
    const type = btn.dataset.more;
    if (btn.classList.contains("loading")) return;
    btn.classList.add("loading");
    const textEl = btn.querySelector(".more-text");
    const originalText = textEl?.textContent || "查看更多";
    if (textEl) textEl.textContent = "加载中";
    try {
      const data = await loadTmdbTrending(300);
      state.tmdbMore = { type, items: data[type] || [], page: 1 };
      renderTmdb();
    } catch (error) {
      toast(`榜单加载失败：${error.message}`);
      btn.classList.remove("loading");
      if (textEl) textEl.textContent = originalText;
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
  const section = $("#tmdbSearchResults");
  const trending = $("#tmdbTrendingContent");
  if (trending) trending.classList.add("hidden");
  if (section) {
    section.classList.remove("hidden");
    const viewContent = section.querySelector(".view-section") || section;
    viewContent.innerHTML = `<div class="empty">正在搜索...</div>`;
  }
  const data = await api(`/api/tmdb/search?q=${encodeURIComponent(query)}`);
  if (state.tmdbSearchQuery !== query) return;
  state.tmdbSearch = data.results || [];
  renderTmdb();
}
