function enhanceIntegrationCards() {
  const pan = document.querySelector('[data-save-settings="115"]');
  if (pan) {
    pan.insertAdjacentHTML("beforeend", `
      <label>扫码登录渠道
        <select id="panQrChannel">
          <option value="web">115生活_网页端 - web</option>
          <option value="ios">115生活_苹果端 - ios</option>
          <option value="115ios">115_苹果端 - 115ios</option>
          <option value="android">115生活_安卓端 - android</option>
          <option value="115android">115_安卓端 - 115android</option>
          <option value="ipad">115生活_苹果平板端 - ipad</option>
          <option value="115ipad">115_苹果平板端 - 115ipad</option>
          <option value="alipaymini">115生活_支付宝小程序 - alipaymini</option>
          <option value="wechatmini">115生活_微信小程序 - wechatmini</option>
          <option value="qandroid">115生活_安卓电视端 - qandroid</option>
          <option value="tv">115生活_TV端 - tv</option>
          <option value="mac">115生活_MAC端 - mac</option>
          <option value="windows">115生活_Windows端 - windows</option>
          <option value="linux">115生活_Linux端 - linux</option>
          <option value="harmony">115生活_鸿蒙端 - harmony</option>
        </select>
      </label>
      <div class="inline-actions">
        <button type="button" class="secondary" id="panQrBtn">115 扫码</button>
        <button type="button" class="secondary" id="panStatusBtn">检查状态</button>
      </div>
      <div class="qr-box" id="panQrBox">尚未生成二维码</div>
    `);
    $("#panQrBtn").addEventListener("click", startPanQr);
    $("#panStatusBtn").addEventListener("click", checkPanStatus);
  }

  const tg = document.querySelector('[data-save-settings="telegram"]');
  if (tg) {
    tg.insertAdjacentHTML("beforeend", `
      <div class="inline-actions">
        <button type="button" class="secondary" id="tgQrBtn">TG 扫码</button>
        <button type="button" class="secondary" id="tgStatusBtn">检查状态</button>
      </div>
      <div class="tg-phone-login">
        <label>手机号 <input id="tgPhone" type="tel" placeholder="+8613800000000" autocomplete="tel" /></label>
        <button type="button" class="secondary" id="tgSendCodeBtn">发送验证码</button>
        <label>验证码 <input id="tgCode" inputmode="numeric" autocomplete="one-time-code" /></label>
        <button type="button" class="secondary" id="tgCodeLoginBtn">验证码登录</button>
      </div>
      <div class="qr-box" id="tgQrBox">尚未生成二维码</div>
    `);
    $("#tgQrBtn").addEventListener("click", startTgQr);
    $("#tgStatusBtn").addEventListener("click", checkTgStatus);
    $("#tgSendCodeBtn").addEventListener("click", sendTgCode);
    $("#tgCodeLoginBtn").addEventListener("click", loginTgCode);
  }

  const loadDialogs = $("#loadTelegramDialogs");
  if (loadDialogs) loadDialogs.addEventListener("click", loadTelegramDialogs);

  const loadFolders = $("#loadPanFolders");
  if (loadFolders) {
    loadFolders.addEventListener("click", () => loadPanFolders(state.panFolder.cid || "0", state.panFolder.path || "/"));
  }

  const folderRoot = $("#panFolderRoot");
  if (folderRoot) folderRoot.addEventListener("click", () => selectPanFolder("0", "/"));

  const proxyForm = document.querySelector('[data-save-settings="proxy"]');
  if (proxyForm) {
    proxyForm.insertAdjacentHTML("beforeend", `
      <div class="proxy-test-toolbar">
        <button type="button" class="secondary" id="proxyTestBtn">延迟测试</button>
        <div class="proxy-test-result" id="proxyTestResult"></div>
      </div>
    `);
    $("#proxyTestBtn").addEventListener("click", testProxyLatency);
  }
}

async function startPanQr() {
  const channel = $("#panQrChannel")?.value || "web";
  const box = $("#panQrBox");
  if (state.panQrTimer) clearInterval(state.panQrTimer);
  box.innerHTML = `<span>正在生成二维码...</span>`;
  try {
    const data = await api("/api/115/qr-login", { method: "POST", body: JSON.stringify({ channel }) });
    box.innerHTML = `<img alt="115 QR" src="${data.qr_url}" onerror="this.replaceWith(Object.assign(document.createElement('span'), {textContent:'二维码图片加载失败，请查看日志里的 115 错误'}))" /><span>打开 115 App 扫码确认后点击检查状态</span>`;
    state.panQrTimer = setInterval(checkPanStatus, 3000);
  } catch (error) {
    box.innerHTML = `<span>二维码生成失败：${escapeHtml(error.message)}</span>`;
  }
}

async function checkPanStatus() {
  const data = await api("/api/115/status");
  const statusText = {
    "0": "等待扫码",
    "1": "已扫码，等待确认",
    "2": "已确认",
    "-1": "二维码已过期",
    "-2": "已取消",
    authorized: "已登录",
    cookie_missing: "未获取到 Cookie",
  }[data.status] || data.status;
  const box = $("#panQrBox");
  const statusInput = document.querySelector('[data-save-settings="115"] [name="qr_login"]');
  if (statusInput) statusInput.value = statusText;
  if (box && data.status !== "authorized") {
    const label = box.querySelector(".qr-status-label");
    if (label) label.textContent = `115 状态：${statusText}`;
    else box.insertAdjacentHTML("beforeend", `<span class="qr-status-label">115 状态：${escapeHtml(statusText)}</span>`);
  }
  if (!state.panQrTimer || data.status === "authorized") toast(`115 状态：${statusText}`);
  if (data.status === "authorized") {
    if (state.panQrTimer) clearInterval(state.panQrTimer);
    state.panQrTimer = null;
    state.settings = await api("/api/settings");
    const cookieInput = document.querySelector('[data-save-settings="115"] [name="cookie"]');
    if (cookieInput && data.cookie) cookieInput.value = data.cookie;
    renderSettings();
    toast("115 Cookie 已自动保存");
  } else if (["-1", "-2", "cookie_missing"].includes(String(data.status))) {
    if (state.panQrTimer) clearInterval(state.panQrTimer);
    state.panQrTimer = null;
  }
}

async function startTgQr() {
  const box = $("#tgQrBox");
  if (state.tgLoginTimer) clearInterval(state.tgLoginTimer);
  box.innerHTML = `<span>正在生成二维码...</span>`;
  try {
    const data = await api("/api/telegram/qr-login", { method: "POST" });
    box.innerHTML = `<img alt="Telegram QR" src="${data.qr_url}" onerror="this.replaceWith(Object.assign(document.createElement('span'), {textContent:'二维码图片加载失败'}))" /><span>用 Telegram 扫码登录</span>`;
    state.tgLoginTimer = setInterval(checkTgStatus, 3000);
  } catch (error) {
    box.innerHTML = `<span>二维码生成失败：${escapeHtml(error.message)}</span>`;
  }
}

async function checkTgStatus() {
  const data = await api("/api/telegram/status");
  const box = $("#tgQrBox");
  if (data.status === "password_required") {
    if (state.tgLoginTimer) clearInterval(state.tgLoginTimer);
    state.tgLoginTimer = null;
    if (box) box.innerHTML = `<span>当前 Telegram 账号开启了两步验证，请先在 Telegram 里关闭两步验证后再登录。</span>`;
  }
  if (data.authorized) {
    if (state.tgLoginTimer) clearInterval(state.tgLoginTimer);
    state.tgLoginTimer = null;
    if (box) box.innerHTML = `<span>Telegram 已登录</span>`;
  } else if (box && data.status && data.status !== "waiting") {
    const label = box.querySelector(".qr-status-label");
    if (label) label.textContent = `Telegram 状态：${data.status}`;
    else box.insertAdjacentHTML("beforeend", `<span class="qr-status-label">Telegram 状态：${escapeHtml(data.status)}</span>`);
  }
  if (!state.tgLoginTimer) toast(data.authorized ? "Telegram 已登录" : `Telegram 未登录：${data.status || "waiting"}`);
}

async function sendTgCode() {
  const phone = $("#tgPhone").value.trim();
  if (!phone) return toast("请输入手机号");
  try {
    await api("/api/telegram/send-code", { method: "POST", body: JSON.stringify({ phone }) });
    toast("验证码已发送");
  } catch (error) {
    toast(`验证码发送失败：${error.message}`);
  }
}

async function loginTgCode() {
  const phone = $("#tgPhone").value.trim();
  const code = $("#tgCode").value.trim();
  if (!phone || !code) return toast("请输入手机号和验证码");
  try {
    const data = await api("/api/telegram/code-login", { method: "POST", body: JSON.stringify({ phone, code }) });
    if (data.status === "password_required") {
      toast("当前 Telegram 账号开启了两步验证，请先关闭后再登录");
      return;
    }
    toast("Telegram 已登录");
  } catch (error) {
    toast(`验证码登录失败：${error.message}`);
  }
}

async function loadTelegramDialogs() {
  const box = $("#telegramDialogList");
  const picker = $("#telegramSources");
  box.classList.remove("hidden");
  box.innerHTML = `<div class="muted">正在读取...</div>`;
  const selected = new Set((box.dataset.selected || "").split(",").filter(Boolean));
  try {
    const status = await api("/api/telegram/status");
    if (!status.authorized) {
      box.innerHTML = `<div class="muted">Telegram 未登录：${escapeHtml(status.status || "not_authorized")}</div>`;
      return;
    }
    const data = await api("/api/telegram/dialogs");
    const dialogs = data.dialogs || [];
    rememberTelegramDialogs(dialogs);
    if (dialogs.length) picker?.querySelectorAll('input[type="hidden"][name="sources"]').forEach((input) => input.remove());
    box.innerHTML = dialogs.length ? dialogs.map((item) => `
      <label>
        <input type="checkbox" name="sources" value="${escapeHtml(item.source)}" ${selected.has(item.source) ? "checked" : ""} />
        <span>${escapeHtml(item.title)}</span>
        <small>${escapeHtml(item.type)}${item.username ? ` @${escapeHtml(item.username)}` : ""}</small>
      </label>
    `).join("") : `<div class="muted">没有读取到群组或频道。</div>`;
  } catch (error) {
    box.innerHTML = `<div class="muted">群组/频道读取失败：${escapeHtml(error.message)}</div>`;
  }
}

function selectPanFolder(cid, path) {
  state.panFolder = { cid: String(cid), path };
  const pathInput = $("#panTargetPath");
  const cidInput = $("#panTargetCid");
  const current = $("#panFolderCurrent");
  if (pathInput) pathInput.value = path;
  if (cidInput) cidInput.value = cid;
  if (current) current.textContent = path;
  toast(`已选择目录：${path}`);
}

async function loadPanFolders(cid = "0", basePath = "/") {
  const box = $("#panFolderList");
  box.innerHTML = `<div class="muted">正在读取目录...</div>`;
  try {
    const data = await api(`/api/115/folders?cid=${encodeURIComponent(cid)}`);
    const folders = data.folders || [];
    const parent = basePath !== "/" ? `<button type="button" class="folder-row" data-cid="0" data-path="/">返回根目录</button>` : "";
    box.innerHTML = parent + (folders.length ? folders.map((item) => {
      const path = `${basePath.replace(/\/$/, "")}/${item.name}`.replace(/^$/, "/");
      return `<button type="button" class="folder-row" data-cid="${escapeHtml(item.id)}" data-path="${escapeHtml(path)}">${escapeHtml(item.name)}</button>`;
    }).join("") : `<div class="muted">当前目录没有子目录。</div>`);
    box.querySelectorAll(".folder-row").forEach((btn) => btn.addEventListener("click", () => {
      selectPanFolder(btn.dataset.cid, btn.dataset.path);
      loadPanFolders(btn.dataset.cid, btn.dataset.path);
    }));
  } catch (error) {
    box.innerHTML = `<div class="muted">目录读取失败：${escapeHtml(error.message)}</div>`;
  }
}

async function testProxyLatency() {
  const form = document.querySelector('[data-save-settings="proxy"]');
  const formData = new FormData(form);
  const url = formData.get("url") || "";
  const modules = formData.getAll("modules");
  const resultBox = $("#proxyTestResult");
  resultBox.innerHTML = `<div class="muted">正在测试...</div>`;
  try {
    const data = await api("/api/proxy/test", { method: "POST", body: JSON.stringify({ url, modules }) });
    const github = data.results.github;
    const google = data.results.google;
    resultBox.innerHTML = `
      <div class="latency-row"><strong>GitHub</strong><span>${github.ok ? `${github.latency_ms} ms` : escapeHtml(github.error)}</span></div>
      <div class="latency-row"><strong>Google</strong><span>${google.ok ? `${google.latency_ms} ms` : escapeHtml(google.error)}</span></div>
    `;
  } catch (error) {
    resultBox.innerHTML = `<div class="muted">${escapeHtml(error.message)}</div>`;
  }
}

boot();
