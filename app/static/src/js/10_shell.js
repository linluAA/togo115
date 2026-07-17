function renderLogin() {
  $("#app").innerHTML = `
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
  const shell = $(".shell");
  if (shell) {
    shell.classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  }
  const userMenu = $(".user-menu");
  if (userMenu) userMenu.classList.toggle("open", state.userMenuOpen);
  const sidebarToggle = $("#sidebarToggle");
  if (sidebarToggle) {
    sidebarToggle.innerHTML = state.sidebarCollapsed ? "&rsaquo;" : "&lsaquo;";
    sidebarToggle.setAttribute("aria-label", state.sidebarCollapsed ? "展开侧边栏" : "收起侧边栏");
  }
}

function renderApp() {
  persistView();
  const current = navItems.find(([key]) => key === state.view) || navItems[0];
  const username = escapeHtml(state.user?.username || "用户");
  const themeLabel = state.theme === "light" ? "切换深色主题" : "切换浅色主题";
  const themeIcon = state.theme === "light" ? "深" : "浅";
  $("#app").innerHTML = `
    <div class="shell ${state.sidebarCollapsed ? "sidebar-collapsed" : ""}">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-mark">115</div>
          <div class="brand-copy"><strong>ToGo115</strong><span>Auto Media</span></div>
        </div>
        <nav class="nav">
          ${navItems.map(([key, label, description, icon]) => `<button class="${state.view === key ? "active" : ""}" data-view="${key}" title="${label}">
            <span class="nav-icon">${icon}</span>
            <span class="nav-copy"><strong>${label}</strong><small>${description}</small></span>
          </button>`).join("")}
        </nav>
        <button type="button" class="sidebar-toggle" id="sidebarToggle" aria-label="${state.sidebarCollapsed ? "展开侧边栏" : "收起侧边栏"}">${state.sidebarCollapsed ? "›" : "‹"}</button>
      </aside>
      <main class="main">
        <header class="topbar">
          <div class="topbar-title"><h2>${current[1]}</h2><p>${current[2]}</p></div>
          <div class="top-actions">
            <button class="icon-action" id="quickLogBtn" title="日志" aria-label="日志">Log</button>
            <div class="user-menu ${state.userMenuOpen ? "open" : ""}">
              <button type="button" class="avatar-btn" id="userMenuBtn" aria-label="账号菜单">${username.slice(0, 1).toUpperCase()}</button>
              <div class="user-menu-panel">
                <div class="user-menu-head">
                  <span class="user-menu-avatar">${username.slice(0, 1).toUpperCase()}</span>
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
  $("#sidebarToggle").addEventListener("click", () => {
    state.sidebarCollapsed = !state.sidebarCollapsed;
    localStorage.setItem("sidebarCollapsed", String(state.sidebarCollapsed));
    updateShellUiState();
  });
  $("#quickLogBtn").addEventListener("click", () => {
    setView("logs");
  });
  $("#userMenuBtn").addEventListener("click", () => {
    state.userMenuOpen = !state.userMenuOpen;
    updateShellUiState();
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
  renderView();
}


function openAccountSecuritySettings() {
  state.settingsTab = "credentials";
  localStorage.setItem("settingsTab", state.settingsTab);
  state.userMenuOpen = false;
  if (state.view === "settings") {
    // Same page: force re-render credentials and focus password for clear feedback.
    updateShellUiState();
    renderSettings();
    focusAccountPasswordField();
    toast("已切换到账号安全");
    return;
  }
  setView("settings");
  // renderApp is sync; focus after shell rebuild.
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
