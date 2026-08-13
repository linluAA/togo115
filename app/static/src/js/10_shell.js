function renderLogin() {
  $("#app").innerHTML = `
    <div class="bg-atmosphere"></div>
    <main class="login">
      <section class="login-card">
        <h1>ToGo115</h1>
        <p>115 网盘资源订阅与追新控制台</p>
        <form id="loginForm">
          <label>账号 <input name="username" autocomplete="username" value="" /></label>
          <label>密码 <input name="password" type="password" autocomplete="current-password" value="" /></label>
          <button type="submit">登录</button>
        </form>
      </section>
    </main>
  `;
  $("#loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api("/api/auth/login", { method: "POST", body: JSON.stringify(Object.fromEntries(form)) });
      state.user = await api("/api/auth/me");
      cacheUser(state.user);
      await refreshBase();
      renderApp();
    } catch (error) {
      toast(error.message);
    }
  });
}

function updateShellUiState() {
  const userMenu = $(".user-menu");
  if (userMenu) userMenu.classList.toggle("open", state.userMenuOpen);
}

function renderApp() {
  persistView();
  const current = navItems.find(([key]) => key === state.view) || navItems[0];
  const username = escapeHtml(state.user?.username || "用户");
  const themeLabel = state.theme === "light" ? "切换深色主题" : "切换浅色主题";
  const themeIcon = state.theme === "light" ? "☀" : "☾";
  const firstLetter = username.slice(0, 1).toUpperCase();
  $("#app").innerHTML = `
    <div class="bg-atmosphere"></div>
    <div class="shell">
      <aside class="sidebar">
        <div class="sidebar-brand">
          <div class="logo">✦</div>
          <span class="brand-text">togo115</span>
        </div>
        <nav class="sidebar-nav">
          ${navItems.map(([key, label, description, icon]) => `<button class="${state.view === key ? "active" : ""} nav-item" data-view="${key}" title="${description}">
            <span class="nav-icon">${icon}</span>
            <span class="nav-label">${label}</span>
          </button>`).join("")}
        </nav>
        <div class="sidebar-bottom">
          <button type="button" class="theme-toggle" id="sidebarThemeBtn">
            <span class="icon">${themeIcon}</span>
            <span>${themeLabel}</span>
          </button>
        </div>
      </aside>
      <main class="main">
        <header class="topbar">
          <div class="topbar-breadcrumb">
            <span>首页</span>
            <span style="color:var(--dim)">/</span>
            <span class="current">${current[1]}</span>
          </div>
          <div class="topbar-spacer"></div>
          <div class="topbar-actions">
            <div class="topbar-search${state.view === "tmdb" ? " hidden" : ""}">
              <span class="search-icon">⌕</span>
              <input type="text" placeholder="搜索片名、关键词..." id="globalSearch">
            </div>
            <div class="user-menu ${state.userMenuOpen ? "open" : ""}">
              <div class="topbar-avatar" id="userMenuBtn" title="账号菜单">${firstLetter}</div>
              <div class="user-menu-panel">
                <div class="user-menu-head">
                  <span class="user-menu-avatar">${firstLetter}</span>
                  <div class="user-menu-meta"><span>当前账号</span><strong>${username}</strong></div>
                </div>
                <div class="user-menu-list">
                  <button type="button" class="user-menu-action" id="themeToggleBtn"><span>${themeIcon}</span><strong>${themeLabel}</strong></button>
                  <button type="button" class="user-menu-action" id="accountSettingsBtn"><span>密</span><strong>修改账号密码</strong></button>
                  <button type="button" class="user-menu-action danger" id="logoutBtn"><span>退</span><strong>退出登录</strong></button>
                </div>
              </div>
            </div>
          </div>
        </header>
        <div id="view"></div>
      </main>
      <nav class="mobile-bottom-nav" aria-label="移动端导航">
        ${navItems.map(([key, label, , icon]) => `<button class="${state.view === key ? "active" : ""}" data-view="${key}" title="${label}">
          <span class="nav-icon">${icon}</span>
          <span>${label}</span>
        </button>`).join("")}
      </nav>
    </div>
  `;
  document.querySelectorAll("[data-view]").forEach((btn) => btn.addEventListener("click", () => {
    setView(btn.dataset.view);
  }));
  $("#userMenuBtn").addEventListener("click", (e) => {
    e.stopPropagation();
    state.userMenuOpen = !state.userMenuOpen;
    updateShellUiState();
  });
  document.addEventListener("click", () => {
    if (state.userMenuOpen) {
      state.userMenuOpen = false;
      updateShellUiState();
    }
  }, { once: false });
  $("#sidebarThemeBtn")?.addEventListener("click", () => {
    toggleTheme();
  });
  $("#accountSettingsBtn")?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    openAccountSecuritySettings();
  });
  $("#themeToggleBtn")?.addEventListener("click", () => {
    state.userMenuOpen = false;
    toggleTheme();
  });
  $("#logoutBtn")?.addEventListener("click", async () => {
    await api("/api/auth/logout", { method: "POST" });
    state.userMenuOpen = false;
    cacheUser(null);
    state.user = null;
    renderLogin();
  });
  $("#globalSearch")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const query = event.currentTarget.value.trim();
    if (!query) return;
    const run = () => {
      const input = $("#tmdbQuery");
      if (input) {
        input.value = query;
        searchTmdb();
      }
    };
    if (state.view === "tmdb") run();
    else {
      setView("tmdb");
      run();
    }
  });
  renderView();
}


function openAccountSecuritySettings() {
  state.settingsTab = "credentials";
  localStorage.setItem("settingsTab", state.settingsTab);
  state.userMenuOpen = false;
  if (state.view === "settings") {
    updateShellUiState();
    renderSettings();
    focusAccountPasswordField();
    toast("已切换到账号安全");
    return;
  }
  setView("settings");
  focusAccountPasswordField();
}

function focusAccountPasswordField() {
  requestAnimationFrame(() => {
    const form = document.querySelector('[data-save-settings="credentials"]');
    const password = form?.querySelector('input[name="password"]');
    const username = form?.querySelector('input[name="username"]');
    const target = password || username;
    if (!target) return;
    try {
      target.focus({ preventScroll: false });
      if (typeof target.select === "function" && target.name === "password") target.select();
    } catch {
      target.focus();
    }
  });
}

function renderView() {
  if (state.view === "dashboard") renderDashboard();
  if (state.view === "tmdb") renderTmdb();
  if (state.view === "emby") renderEmby();
  if (state.view === "subscriptions") renderSubscriptions();
  if (state.view === "logs") renderLogs();
  if (state.view === "settings") renderSettings();
}

function sectionTitle(type) {
  return type === "movie" ? "热门电影" : "热门剧集";
}

function tmdbMorePageSize() {
  const viewWidth = $("#view")?.clientWidth || window.innerWidth || 1200;
  const cardMinWidth = 144;
  const gap = 18;
  const columns = Math.max(2, Math.floor((viewWidth + gap) / (cardMinWidth + gap)));
  return Math.min(72, columns * Math.ceil(TMDB_MORE_MIN_PAGE_SIZE / columns));
}