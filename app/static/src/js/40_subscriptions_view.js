async function renderSubscriptions() {
  if (!state.subscriptionsEmbySynced) {
    state.subscriptionsEmbySynced = true;
    $("#view").innerHTML = `<div class="empty">正在同步订阅入库状态...</div>`;
    try {
      const result = await api("/api/subscriptions/sync-emby", { method: "POST" });
      if (result?.updated) {
        state.subscriptions = await api("/api/subscriptions");
      }
    } catch {
      // The manual sync button still exposes the error to the user when needed.
    }
  }
  $("#view").innerHTML = `
    ${subscriptionCards()}
    ${failedTaskPanel()}
    <section class="section">
      <h3>最近发现的资源</h3>
      ${resourceTable()}
    </section>
  `;
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
  $("#subscriptionReset")?.addEventListener("click", () => {
    state.subscriptionType = "all";
    state.subscriptionStatus = "all";
    renderSubscriptions();
  });
  $("#syncEmbySubscriptions")?.addEventListener("click", async () => {
    try {
      const result = await api("/api/subscriptions/sync-emby", { method: "POST" });
      if (result.running) {
        toast(result.queued === false ? "媒体库同步正在后台运行，请稍后刷新" : "媒体库同步已加入后台队列，请稍后刷新");
        return;
      }
      await refreshSubscriptionData();
      renderSubscriptions();
      toast(result.ok ? `媒体库同步完成，匹配 ${result.matched || 0} 个订阅` : `媒体库同步失败：${result.error || "请查看日志"}`);
    } catch (error) {
      toast(`媒体库同步失败：${error.message}`);
    }
  });
  $("#searchAllSubscriptions")?.addEventListener("click", async () => {
    const button = $("#searchAllSubscriptions");
    button.disabled = true;
    button.textContent = "搜索中";
    try {
      const result = await api("/api/subscriptions/search-all", { method: "POST" });
      if (result.running) {
        toast(result.queued === false ? "搜索全部正在后台运行，请查看日志进度" : "搜索全部已进入后台，请查看日志进度");
        scheduleSubscriptionSoftRefresh(result.queued === false ? 3000 : 5000);
      } else {
        await refreshSubscriptionData();
        renderSubscriptions();
        toast(`搜索完成，检查 ${result.searched || 0} 个订阅，新增 ${result.count || 0} 条资源${result.failed ? `，失败 ${result.failed} 个` : ""}`);
      }
    } catch (error) {
      toast(`搜索失败：${error.message}`);
    } finally {
      button.disabled = false;
      button.textContent = "搜索全部";
    }
  });
  $("#toggleCancelSubscriptions")?.addEventListener("click", () => {
    state.subscriptionCancelMode = !state.subscriptionCancelMode;
    state.selectedSubscriptionIds.clear();
    renderSubscriptions();
  });
  $("#confirmCancelSubscriptions")?.addEventListener("click", async () => {
    const ids = [...state.selectedSubscriptionIds];
    if (!ids.length) return toast("请选择需要取消的订阅");
    await api("/api/subscriptions/bulk-delete", { method: "POST", body: JSON.stringify({ ids }) });
    state.subscriptionCancelMode = false;
    state.selectedSubscriptionIds.clear();
    await refreshSubscriptionData();
    renderSubscriptions();
    toast(`已取消 ${ids.length} 个订阅`);
  });
  document.querySelectorAll("[data-select-subscription]").forEach((btn) => btn.addEventListener("change", () => {
    const id = Number(btn.dataset.selectSubscription);
    if (btn.checked) state.selectedSubscriptionIds.add(id);
    else state.selectedSubscriptionIds.delete(id);
  }));
  $("#toggleResourceDelete")?.addEventListener("click", () => {
    state.resourceDeleteMode = !state.resourceDeleteMode;
    state.selectedResourceIds.clear();
    renderSubscriptions();
  });
  document.querySelectorAll("[data-select-resource]").forEach((btn) => btn.addEventListener("change", () => {
    const id = Number(btn.dataset.selectResource);
    if (btn.checked) state.selectedResourceIds.add(id);
    else state.selectedResourceIds.delete(id);
    renderSubscriptions();
  }));
  $("#confirmResourceDelete")?.addEventListener("click", async () => {
    const ids = [...state.selectedResourceIds];
    if (!ids.length) return toast("请选择需要删除的资源");
    const res = await api("/api/resources/bulk-delete", { method: "POST", body: JSON.stringify({ ids }) });
    state.selectedResourceIds.clear();
    state.resourceDeleteMode = false;
    await refreshSubscriptionData();
    renderSubscriptions();
    toast(`已删除 ${res.deleted || 0} 条资源`);
  });
  $("#clearResources")?.addEventListener("click", async () => {
    if (!confirm("确定清空最近发现的所有资源吗？")) return;
    const res = await api("/api/resources/clear", { method: "POST" });
    state.selectedResourceIds.clear();
    state.resourceDeleteMode = false;
    await refreshSubscriptionData();
    renderSubscriptions();
    toast(`已清空 ${res.deleted || 0} 条资源`);
  });
  document.querySelectorAll("[data-delete]").forEach((btn) => btn.addEventListener("click", async () => {
    state.subscriptionCancelMode = true;
    state.selectedSubscriptionIds = new Set([Number(btn.dataset.delete)]);
    renderSubscriptions();
  }));
  document.querySelectorAll("[data-search]").forEach((btn) => btn.addEventListener("click", async () => {
    const res = await api(`/api/subscriptions/${btn.dataset.search}/search`, { method: "POST" });
    toast(res.running ? "订阅搜索已进入后台，请查看日志进度" : `搜索完成，新增 ${res.count || 0} 条资源`);
  }));
  document.querySelectorAll("[data-status-menu]").forEach((btn) => btn.addEventListener("click", (event) => {
    event.stopPropagation();
    const id = String(btn.dataset.statusMenu || "");
    const menu = document.querySelector(`[data-status-dropdown="${CSS.escape(id)}"]`);
    if (!menu) return;
    const open = !menu.classList.contains("hidden");
    document.querySelectorAll("[data-status-dropdown]").forEach((el) => {
      el.classList.add("hidden");
      const trigger = document.querySelector(`[data-status-menu="${CSS.escape(el.dataset.statusDropdown || "")}"]`);
      if (trigger) trigger.setAttribute("aria-expanded", "false");
    });
    if (!open) {
      menu.classList.remove("hidden");
      btn.setAttribute("aria-expanded", "true");
    }
  }));
  document.querySelectorAll("[data-set-status]").forEach((btn) => btn.addEventListener("click", async (event) => {
    event.stopPropagation();
    const id = Number(btn.dataset.setStatus);
    const status = String(btn.dataset.status || "");
    if (!id || !status) return;
    document.querySelectorAll("[data-status-dropdown]").forEach((el) => el.classList.add("hidden"));
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
  if (!window.__subscriptionStatusMenuBound) {
    window.__subscriptionStatusMenuBound = true;
    document.addEventListener("click", () => {
      document.querySelectorAll("[data-status-dropdown]").forEach((el) => {
        el.classList.add("hidden");
        const trigger = document.querySelector(`[data-status-menu="${CSS.escape(el.dataset.statusDropdown || "")}"]`);
        if (trigger) trigger.setAttribute("aria-expanded", "false");
      });
    });
  }

  document.querySelectorAll("[data-edit]").forEach((btn) => btn.addEventListener("click", async () => {
    const id = btn.dataset.edit;
    const keywords = prompt("输入新的关键词，多个用逗号分隔");
    if (keywords === null) return;
    await api(`/api/subscriptions/${id}`, { method: "PUT", body: JSON.stringify({ keywords: keywords.split(",").map((x) => x.trim()).filter(Boolean) }) });
    await refreshSubscriptionData();
    renderSubscriptions();
  }));
  document.querySelectorAll("[data-edit-rules]").forEach((btn) => btn.addEventListener("click", async () => {
    const subscription = state.subscriptions.find((item) => Number(item.id) === Number(btn.dataset.editRules));
    if (!subscription) return;
    await editQualityRules(subscription);
  }));
  document.querySelectorAll("[data-deliver]").forEach((btn) => btn.addEventListener("click", async () => {
    const res = await api(`/api/resources/${btn.dataset.deliver}/deliver`, { method: "POST" });
    await refreshSubscriptionData();
    renderSubscriptions();
    toast(res.ok ? "已重新投递" : "投递失败，请看日志");
  }));
  $("#loadMoreResources")?.addEventListener("click", async () => {
    state.resourcesLimit += 40;
    if (state.resources.length < state.resourcesLimit) {
      const more = await api(`/api/resources?limit=80&offset=${state.resources.length}`);
      const seen = new Set(state.resources.map((item) => Number(item.id)));
      state.resources = [...state.resources, ...more.filter((item) => !seen.has(Number(item.id)))];
    }
    renderSubscriptions();
  });
  $("#retryFailedTasks")?.addEventListener("click", async () => {
    const button = $("#retryFailedTasks");
    button.disabled = true;
    button.textContent = "重试中";
    try {
      const res = await api("/api/tasks/retry-failed", { method: "POST" });
      await refreshSubscriptionData();
      renderSubscriptions();
      toast(`已重试 ${res.retried || 0} 个，成功 ${res.delivered || 0} 个`);
    } catch (error) {
      button.disabled = false;
      button.textContent = "重试全部";
      toast(`重试失败：${error.message}`);
    }
  });
}
