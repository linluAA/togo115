async function saveSettings(event) {
  event.preventDefault();
  const key = event.currentTarget.dataset.saveSettings;
  const value = Object.fromEntries(new FormData(event.currentTarget));
  const moduleValues = new FormData(event.currentTarget).getAll("modules");
  if (key === "proxy") value.modules = moduleValues;
  const sourceValues = new FormData(event.currentTarget).getAll("sources");
  if (key === "telegram") value.sources = sourceValues.join(",");
  if (key === "credentials") {
    await api("/api/auth/credentials", { method: "PUT", body: JSON.stringify(value) });
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch {
      // Session may already be invalid after credential change.
    }
    cacheUser(null);
    state.user = null;
    state.userMenuOpen = false;
    toast("账号密码已更新，请重新登录");
    renderLogin();
    return;
  }
  await api(`/api/settings/${key}`, { method: "PUT", body: JSON.stringify({ value }) });
  state.settings = await api("/api/settings");
  toast("已保存");
  if (key === "telegram") renderSettings();
}

async function exportBackup() {
  const data = await api("/api/backup/export");
  state.backupText = JSON.stringify(data, null, 2);
  const textarea = $("#backupText");
  if (textarea) textarea.value = state.backupText;
  toast("备份已导出");
}

async function importBackup() {
  const textarea = $("#backupText");
  const text = textarea?.value.trim() || "";
  if (!text) return toast("请先粘贴备份 JSON");
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    return toast("备份 JSON 格式错误");
  }
  const result = await api("/api/backup/import", { method: "POST", body: JSON.stringify(payload) });
  await refreshBase();
  toast(`导入完成：设置 ${result.settings || 0} 项，订阅 ${result.subscriptions || 0} 个`);
  renderSettings();
}
