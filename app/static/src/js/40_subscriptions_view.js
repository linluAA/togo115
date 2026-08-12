
function closeSubscriptionStatusMenus() {
  document.querySelectorAll("[data-status-dropdown]").forEach((el) => {
    el.classList.add("hidden");
    el.style.left = "";
    el.style.top = "";
    el.style.right = "";
    const trigger = document.querySelector(`[data-status-menu="${CSS.escape(el.dataset.statusDropdown || "")}"]`);
    if (trigger) trigger.setAttribute("aria-expanded", "false");
  });
  document.querySelectorAll(".sub-card.is-status-open").forEach((card) => card.classList.remove("is-status-open"));
}

async function renderSubscriptions() {
  if (!state.subscriptionsEmbySynced) {
    state.subscriptionsEmbySynced = true;
    $("#view").innerHTML = `<div class="empty-state"><div class="empty-icon">◌</div><h3>正在同步订阅入库状态...</h3></div>`;
    try {
      const result = await api("/api/subscriptions/sync-emby", { method: "POST" });
      if (result?.updated) {
        state.subscriptions = await api("/api/subscriptions");
      }
    } catch {}
  }
  const filtered = state.subscriptions.filter((item) => {
    const matchType = state.subscriptionType === "all" || item.media_type === state.subscriptionType;
    const matchStatus = state.subscriptionStatus === "all" || item.status === state.subscriptionStatus;
    return matchType && matchStatus;
  });
  const resources = (state.resources || []).slice(0, 20);
  const root = $("#view");
  root.innerHTML = `
    <div class="toolbar view-section">
      <button class="btn btn-secondary" id="searchAllSubscriptions">搜索全部</button>
      <button class="btn btn-secondary" id="syncEmbySubscriptions">同步媒体库</button>
      <div class="toolbar-filters">
        <select id="subscriptionStatusFilter" style="background:var(--surface);border:1px solid var(--line);border-radius:6px;color:var(--ink-soft);padding:6px 10px;font-size:12px;height:32px;outline:none">
          <option value="all" ${state.subscriptionStatus === "all" ? "selected" : ""}>全部状态</option>
          <option value="active" ${state.subscriptionStatus === "active" ? "selected" : ""}>订阅中</option>
          <option value="paused" ${state.subscriptionStatus === "paused" ? "selected" : ""}>已暂停</option>
        </select>
        <select id="subscriptionTypeFilter" style="background:var(--surface);border:1px solid var(--line);border-radius:6px;color:var(--ink-soft);padding:6px 10px;font-size:12px;height:32px;outline:none">
          <option value="all" ${state.subscriptionType === "all" ? "selected" : ""}>全部类型</option>
          <option value="tv" ${state.subscriptionType === "tv" ? "selected" : ""}>剧集</option>
          <option value="movie" ${state.subscriptionType === "movie" ? "selected" : ""}>电影</option>
        </select>
      </div>
    </div>
    ${subscriptionCards(filtered)}
    <div class="section-header view-section">
      <h2>最近资源</h2>
      <button class="section-action" id="resourceManageBtn">管理资源 →</button>
    </div>
    <div class="resource-list view-section">
      ${resources.length ? resources.map((item) => {
        const status = String(item.status || "pending").toLowerCase();
        const statusText = status === "delivered" ? "已投递" : (status === "failed" ? "下载失败" : "待确认");
        const statusClass = status === "delivered" ? "delivered" : (status === "failed" ? "failed" : "pending");
        const iconClass = item.source === "telegram" ? "telegram" : (item.source === "rss" ? "rss" : "magnet");
        const iconText = item.source === "telegram" ? "TG" : (item.source === "rss" ? "RSS" : "M");
        return `<div class="resource-item">
          <div class="r-icon ${iconClass}">${iconText}</div>
          <div class="r-info">
            <div class="r-title">${escapeHtml(item.display_title || item.subscription_title || item.title || "资源")}</div>
            <div class="r-meta"><span>${escapeHtml(item.source || "未知")}</span>${item.file_size ? `<span>${escapeHtml(item.file_size)}</span>` : ""}</div>
          </div>
          <span class="r-status ${statusClass}">${statusText}</span>
        </div>`;
      }).join("") : `<div class="empty-state"><div class="empty-icon">◌</div><h3>暂无资源</h3></div>`}
    </div>
  `;
  bindSubscriptionEvents();
}

function bindSubscriptionEvents() {
  const typeFilter = $("#subscriptionTypeFilter");
  const statusFilter = $("#subscriptionStatusFilter");
  if (typeFilter) typeFilter.addEventListener("change", () => {
    state.subscriptionType = typeFilter.value;
    renderSubscriptions();
  });
  if (statusFilter) statusFilter.addEventListener("change", () => {
    state.subscriptionStatus = statusFilter.value;
    renderSubscriptions();
  });
  $("#searchAllSubscriptions")?.addEventListener("click", async () => {
    const button = $("#searchAllSubscriptions");
    button.disabled = true;
    button.textContent = "搜索中";
    try {
      const result = await api("/api/subscriptions/search-all", { method: "POST" });
      if (result.running) {
        toast(result.queued === false ? "搜索全部正在后台运行，请查看日志进度" : "搜索全部已进入后台，请查看日志进度");
      } else {
        await refreshSubscriptionData();
        renderSubscriptions();
        toast(`搜索完成，检查 ${result.searched || 0} 个订阅，新增 ${result.count || 0} 条资源`);
      }
    } catch (error) {
      toast(`搜索失败：${error.message}`);
    } finally {
      button.disabled = false;
      button.textContent = "搜索全部";
    }
  });
  $("#syncEmbySubscriptions")?.addEventListener("click", async () => {
    try {
      const result = await api("/api/subscriptions/sync-emby", { method: "POST" });
      toast(result.ok ? `媒体库同步完成，匹配 ${result.matched || 0} 个订阅` : `媒体库同步失败：${result.error || "请查看日志"}`);
      await refreshSubscriptionData();
      renderSubscriptions();
    } catch (error) {
      toast(`媒体库同步失败：${error.message}`);
    }
  });
  document.querySelectorAll("[data-set-status]").forEach((btn) => btn.addEventListener("click", async (event) => {
    event.stopPropagation();
    const id = Number(btn.dataset.setStatus);
    const status = String(btn.dataset.status || "");
    if (!id || !status) return;
    closeSubscriptionStatusMenus();
    try {
      if (status === "completed") {
        await api(`/api/subscriptions/${id}`, { method: "DELETE" });
        toast("已标记完结并移除订阅");
      } else {
        await api(`/api/subscriptions/${id}`, { method: "PUT", body: JSON.stringify({ status }) });
        toast(status === "paused" ? "已暂停订阅" : "已恢复订阅中");
      }
      await refreshSubscriptionData();
      renderSubscriptions();
    } catch (error) {
      toast(`状态更新失败：${error.message}`);
    }
  }));
  document.querySelectorAll("[data-status-menu]").forEach((btn) => btn.addEventListener("click", (event) => {
    event.stopPropagation();
    const id = String(btn.dataset.statusMenu || "");
    const menu = document.querySelector(`[data-status-dropdown="${CSS.escape(id)}"]`);
    if (!menu) return;
    const open = !menu.classList.contains("hidden");
    closeSubscriptionStatusMenus();
    if (open) return;
    const rect = btn.getBoundingClientRect();
    const menuWidth = Math.max(112, menu.offsetWidth || 112);
    const left = Math.min(window.innerWidth - menuWidth - 8, Math.max(8, rect.right - menuWidth));
    const top = Math.min(window.innerHeight - 8, rect.bottom + 6);
    menu.style.left = `${Math.round(left)}px`;
    menu.style.top = `${Math.round(top)}px`;
    menu.style.right = "auto";
    menu.classList.remove("hidden");
    btn.setAttribute("aria-expanded", "true");
  }));
  if (!window.__subscriptionStatusMenuBound) {
    window.__subscriptionStatusMenuBound = true;
    document.addEventListener("click", () => closeSubscriptionStatusMenus());
    window.addEventListener("resize", () => closeSubscriptionStatusMenus());
    window.addEventListener("scroll", () => closeSubscriptionStatusMenus(), true);
  }
}

async function editQualityRules(subscription) {
  const rules = subscription.quality_rules || {};
  const preferred = prompt("优先质量，多个用逗号分隔（例如：2160p,1080p）", (rules.preferred_quality || []).join(", "));
  if (preferred === null) return;
  const excludes = prompt("排除词，多个用逗号分隔（例如：TC,枪版,无字幕）", (rules.exclude_keywords || []).join(", "));
  if (excludes === null) return;
  const groups = prompt("压制组偏好/限定，多个用逗号分隔（留空表示不限）", (rules.release_groups || []).join(", "));
  if (groups === null) return;
  const acceptMode = prompt("资源形式：all=全部，pack=只要合集，single=只要单集", rules.accept_mode || "all");
  if (acceptMode === null) return;
  const split = (value) => value.split(/[,，\n\r]+/).map((item) => item.trim()).filter(Boolean);
  const qualityRules = {
    preferred_quality: split(preferred),
    exclude_keywords: split(excludes),
    release_groups: split(groups),
    accept_mode: ["all", "pack", "single"].includes(String(acceptMode).trim().toLowerCase()) ? String(acceptMode).trim().toLowerCase() : "all",
  };
  await api(`/api/subscriptions/${subscription.id}`, { method: "PUT", body: JSON.stringify({ quality_rules: qualityRules }) });
  await refreshSubscriptionData();
  renderSubscriptions();
  toast("质量规则已保存");
}
