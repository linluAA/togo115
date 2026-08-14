const DASHBOARD_HERO_ROTATE_MS = 20000;

function stopDashboardHeroRotation() {
  if (state.dashboardHeroTimer) {
    clearInterval(state.dashboardHeroTimer);
    state.dashboardHeroTimer = null;
  }
}

function dashboardHeroPool() {
  const pool = [];
  const seen = new Set();
  for (const item of [...(state.tmdbTrending?.tv || []), ...(state.tmdbTrending?.movie || [])]) {
    if (!item || !item.id) continue;
    const key = `${item.media_type || (item.title ? "movie" : "tv")}-${item.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    pool.push(item);
  }
  return pool;
}

function dashboardEscapeHtml(value) {
  return escapeHtml(value);
}

function dashboardYear(item) {
  return (item.first_air_date || item.release_date || "").slice(0, 4) || "新近热门";
}

function dashboardMediaType(item) {
  return item.media_type === "movie" || item.title ? "movie" : "tv";
}

function dashboardHeroPayload(item) {
  const type = dashboardMediaType(item);
  const id = `${type}-${item.id}`;
  state.mediaPayloads.set(id, {
    title: item.name || item.title || "热门内容",
    media_type: type,
    tmdb_id: item.id,
    poster_url: posterUrl(item),
    overview: item.overview || "",
    release_year: Number.parseInt(dashboardYear(item), 10) || null,
    keywords: [item.name || item.title || ""],
  });
  return id;
}

function applyDashboardHero(item) {
  const hero = $("#dashboardHero");
  if (!hero || !item) return;
  const title = item.name || item.title || "热门内容";
  const year = dashboardYear(item);
  const type = dashboardMediaType(item);
  const heroOverlay = state.theme === "light"
    ? "linear-gradient(160deg, rgba(248,251,252,.96), rgba(248,251,252,.80) 60%, rgba(248,251,252,.55))"
    : "linear-gradient(160deg, rgba(11,17,23,.94), rgba(11,17,23,.72) 65%, rgba(11,17,23,.45))";
  hero.style.backgroundImage = `${heroOverlay}, url('${backdropUrl(item)}')`;
  hero.style.backgroundSize = "cover";
  hero.style.backgroundPosition = "center";
  hero.querySelector(".hero-content").innerHTML = `
    <div class="hero-tag">✦ 今日推荐</div>
    <h1>${dashboardEscapeHtml(title)}</h1>
    <p>${dashboardEscapeHtml(item.overview || `暂无简介 · ${year}${type === "movie" ? " · 电影" : " · 剧集"}`)}</p>
  `;
  const dots = hero.querySelectorAll(".hero-dots span");
  dots.forEach((dot, index) => {
    dot.classList.toggle("active", index === state.dashboardHeroIndex);
  });
}

function rotateDashboardHeroOnce() {
  if (state.view !== "dashboard") {
    stopDashboardHeroRotation();
    return;
  }
  const pool = dashboardHeroPool();
  if (pool.length <= 1) return;
  state.dashboardHeroIndex = (Number(state.dashboardHeroIndex || 0) + 1) % pool.length;
  applyDashboardHero(pool[state.dashboardHeroIndex]);
}

function startDashboardHeroRotation() {
  stopDashboardHeroRotation();
  const pool = dashboardHeroPool();
  state.dashboardHeroIndex = 0;
  if (pool.length > 1) {
    state.dashboardHeroTimer = setInterval(rotateDashboardHeroOnce, DASHBOARD_HERO_ROTATE_MS);
  }
}

function dashboardStats() {
  const subscriptions = state.subscriptions || [];
  const resources = state.resources || [];
  const failedTasks = state.failedTasks || [];
  const active = subscriptions.filter((item) => item.status === "active").length;
  const completed = subscriptions.filter((item) => item.status === "completed" || (item.media_type === "movie" ? Boolean(item.in_library) : Boolean(item.tmdb_total_count && item.emby_count >= item.tmdb_total_count))).length;
  const totalEpisodes = subscriptions.reduce((sum, item) => sum + Number(item.emby_count || 0), 0);
  const pendingResources = resources.filter((item) => {
    const status = String(item.status || "pending").toLowerCase();
    return status === "pending" || status === "pending_recheck" || status === "delivery_failed_retryable";
  }).length;
  const delivered = resources.filter((item) => String(item.status || "").toLowerCase() === "delivered").length;
  const health = resources.length
    ? Math.max(0, Math.min(100, Math.round((delivered / resources.length) * 100)))
    : (failedTasks.length ? 60 : 100);
  return {
    active,
    completed,
    totalEpisodes,
    pendingResources,
    resourcesTotal: resources.length,
    failedTasks: failedTasks.length,
    health,
  };
}

function dashboardActivityItems() {
  const items = [];
  const subscriptions = state.subscriptions || [];
  const resources = state.resources || [];
  const failedTasks = state.failedTasks || [];
  const seen = new Set();

  const push = (text, time, color) => {
    const key = `${color}|${time}`;
    if (seen.has(key) || items.length >= 6) return;
    seen.add(key);
    items.push({ text, time, color });
  };

  for (const task of failedTasks.slice(0, 2)) {
    push(`<strong>${dashboardEscapeHtml(task.subscription_title || task.title || "资源")}</strong> 投递失败 · 已重试 ${dashboardEscapeHtml(task.retry_count || 0)} 次`, "等待重试", "var(--rose)");
  }
  const recent = [...resources].sort((a, b) => Number(b.id || 0) - Number(a.id || 0));
  for (const resource of recent.slice(0, 3)) {
    const status = String(resource.status || "pending").toLowerCase();
    const statusText = status === "delivered" ? "已投递" : (status === "failed" ? "下载失败" : "新资源待确认");
    const color = status === "delivered" ? "var(--green)" : (status === "failed" ? "var(--rose)" : "var(--amber)");
    push(`<strong>${dashboardEscapeHtml(resource.display_title || resource.subscription_title || resource.title || "资源")}</strong> ${statusText}`, "最近", color);
  }
  const activeTitles = subscriptions.filter((item) => item.status === "active").slice(0, 3);
  for (const sub of activeTitles) {
    push(`订阅 <strong>${dashboardEscapeHtml(sub.title)}</strong> 正在自动追新中`, "订阅中", "var(--teal)");
  }
  return items;
}

async function renderDashboard() {
  const root = $("#view");
  root.innerHTML = `
    <div class="hero-banner view-section" id="dashboardHero">
      <div class="hero-bg"></div>
      <div class="hero-content">
        <div class="hero-tag">✦ 今日推荐</div>
        <h1>正在读取推荐...</h1>
        <p>正在从 TMDB 榜单加载今日推荐内容。</p>
      </div>
      <div class="hero-dots"><span class="active"></span><span></span><span></span><span></span></div>
    </div>
    <div class="stats-grid view-section" id="dashboardStats">${dashboardStatsGrid()}</div>
    <div class="section-header view-section">
      <h2>最近动态</h2>
      <button class="section-action" id="dashboardAllActivity">查看全部 →</button>
    </div>
    <div class="activity-feed view-section" id="dashboardActivity">
      ${dashboardActivityItems().map((item) => `
        <div class="activity-item">
          <span class="a-dot" style="background:${item.color}"></span>
          <span class="a-text">${item.text}</span>
          <span class="a-time">${dashboardEscapeHtml(item.time)}</span>
        </div>`).join("") || `<div class="empty-state"><div class="empty-icon">◌</div><h3>暂无动态</h3><p>收藏或订阅一部剧集后，这里会出现追踪动态。</p></div>`}
    </div>
  `;
  document.querySelectorAll("#dashboardStats .stat-card").forEach((card) => {
    card.addEventListener("click", () => {
      const target = card.dataset.target;
      if (target) setView(target);
    });
  });
  $("#dashboardAllActivity")?.addEventListener("click", () => setView("logs"));
  document.querySelectorAll('#dashboardActivity [data-goto]').forEach((el) => {
    el.addEventListener("click", () => setView(el.dataset.goto));
  });
  startDashboardHeroRotation();
  const pool = dashboardHeroPool();
  if (pool.length) {
    applyDashboardHero(pool[state.dashboardHeroIndex]);
  } else {
    stopDashboardHeroRotation();
    const hero = $("#dashboardHero");
    if (hero) {
      hero.querySelector(".hero-content").innerHTML = `
        <div class="hero-tag">✦ 欢迎回来</div>
        <h1>togo115 媒体控制台</h1>
        <p>管理订阅、追踪资源、同步媒体库 — 一切尽在掌控。</p>`;
    }
    try {
      const data = await loadTmdbTrending(20);
      if (state.view !== "dashboard" || !$("#dashboardHero")) return;
      const heroPool2 = dashboardHeroPool();
      if (heroPool2.length) {
        state.dashboardHeroIndex = 0;
        applyDashboardHero(heroPool2[0]);
        const heroEl = $("#dashboardHero");
        heroEl?.querySelector(".hero-content")?.querySelector(".hero-tag") && (heroEl.querySelector(".hero-tag").textContent = "✦ 今日推荐");
        startDashboardHeroRotation();
      }
    } catch {
      // TMDB 不可用时保持欢迎文案。
    }
  }
}

function dashboardStatsGrid() {
  const stats = dashboardStats();
  const cards = [
    { label: "订阅中", value: String(stats.active), change: `↑ ${stats.active + stats.completed} 个订阅`, color: "var(--green)", target: "subscriptions" },
    { label: "已入库", value: String(stats.completed), change: `${stats.totalEpisodes} 个媒体`, color: "var(--muted)", target: "emby" },
    { label: "待发现", value: String(stats.pendingResources), change: `${stats.resourcesTotal} 条资源`, color: "var(--amber)", target: "subscriptions" },
    { label: "健康度", value: `${stats.health}%`, change: stats.failedTasks ? `${stats.failedTasks} 个来源待处理` : "一切正常", color: stats.failedTasks ? "var(--amber)" : "var(--green)", target: "logs" },
  ];
  return cards.map((card) => `
    <div class="stat-card" data-target="${card.target}">
      <div class="stat-accent"></div>
      <div class="stat-label">${card.label}</div>
      <div class="stat-value">${card.value}</div>
      <div class="stat-change" style="color:${card.color}">${card.change}</div>
    </div>`).join("");
}