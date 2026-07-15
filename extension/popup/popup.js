/**
 * xhs-feishu-sync — Popup 逻辑
 *
 * 管理：飞书凭证配置、监控账号列表、采集触发、状态展示。
 * 数据存储：chrome.storage.local
 * 后端通信：fetch → localhost:9527
 */

const API = "http://localhost:9527";

// ═══════════════════════════════════════════════════
// DOM refs
// ═══════════════════════════════════════════════════

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const el = {
  backendDot: $("#backendDot"),
  backendStatus: $("#backendStatus"),
  appId: $("#appId"),
  appSecret: $("#appSecret"),
  bitableToken: $("#bitableToken"),
  toggleSecret: $("#toggleSecret"),
  btnVerify: $("#btnVerify"),
  feishuMsg: $("#feishuMsg"),
  accountList: $("#accountList"),
  newAccountId: $("#newAccountId"),
  newXhsUserId: $("#newXhsUserId"),
  btnAddAccount: $("#btnAddAccount"),
  btnCollect: $("#btnCollect"),
  collectMsg: $("#collectMsg"),
  lastRun: $("#lastRun"),
};

// ═══════════════════════════════════════════════════
// Init
// ═══════════════════════════════════════════════════

document.addEventListener("DOMContentLoaded", async () => {
  await loadConfig();
  await loadAccounts();
  checkBackend();
  renderAccountList();

  // Event bindings
  el.btnVerify.addEventListener("click", verifyAndSave);
  el.btnAddAccount.addEventListener("click", addAccount);
  el.btnCollect.addEventListener("click", triggerCollect);
  el.toggleSecret.addEventListener("click", togglePassword);

  // Collapsible sections
  bindCollapse("feishuHeader", "feishuBody", "feishuToggle");
  bindCollapse("accountsHeader", "accountsBody", "accountsToggle");

  // Enter key to add account
  el.newXhsUserId.addEventListener("keydown", (e) => {
    if (e.key === "Enter") addAccount();
  });
});

// ═══════════════════════════════════════════════════
// Backend health check
// ═══════════════════════════════════════════════════

async function checkBackend() {
  try {
    const res = await fetch(`${API}/health`);
    const data = await res.json();
    if (data.status === "ok") {
      setBackendStatus("online", "后端运行中");
    } else {
      setBackendStatus("offline", "后端异常");
    }
    return true;
  } catch {
    setBackendStatus("offline", "后端未启动 — 请运行 xhs-feishu-server");
    return false;
  }
}

function setBackendStatus(state, text) {
  el.backendDot.className = `dot ${state}`;
  el.backendStatus.textContent = text;
}

// ═══════════════════════════════════════════════════
// Feishu Config
// ═══════════════════════════════════════════════════

async function loadConfig() {
  const stored = await chrome.storage.local.get(["feishu"]);
  if (stored.feishu) {
    el.appId.value = stored.feishu.app_id || "";
    el.appSecret.value = stored.feishu.app_secret || "";
    el.bitableToken.value = stored.feishu.bitable_app_token || "";
  }
}

async function verifyAndSave() {
  el.btnVerify.disabled = true;
  el.btnVerify.textContent = "验证中...";
  el.feishuMsg.className = "msg info";
  el.feishuMsg.textContent = "正在连接飞书...";

  const config = {
    app_id: el.appId.value.trim(),
    app_secret: el.appSecret.value.trim(),
    bitable_app_token: el.bitableToken.value.trim(),
    bot_webhook_url: "",
  };

  if (!config.app_id || !config.app_secret || !config.bitable_app_token) {
    el.feishuMsg.className = "msg error";
    el.feishuMsg.textContent = "请填写所有字段";
    el.btnVerify.disabled = false;
    el.btnVerify.textContent = "🔗 验证并保存";
    return;
  }

  try {
    const res = await fetch(`${API}/config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });

    if (res.ok) {
      await chrome.storage.local.set({ feishu: config });
      el.feishuMsg.className = "msg success";
      el.feishuMsg.textContent = "✅ 飞书连接成功，配置已保存";
    } else {
      const err = await res.json();
      el.feishuMsg.className = "msg error";
      el.feishuMsg.textContent = `❌ ${err.detail || "连接失败"}`;
    }
  } catch {
    el.feishuMsg.className = "msg error";
    el.feishuMsg.textContent = "❌ 无法连接后端，请确认 xhs-feishu-server 已启动";
  }

  el.btnVerify.disabled = false;
  el.btnVerify.textContent = "🔗 验证并保存";
}

// ═══════════════════════════════════════════════════
// Accounts
// ═══════════════════════════════════════════════════

async function loadAccounts() {
  const stored = await chrome.storage.local.get(["accounts"]);
  return stored.accounts || [];
}

async function saveAccounts(accounts) {
  await chrome.storage.local.set({ accounts });
}

async function addAccount() {
  const id = el.newAccountId.value.trim();
  const xhsId = el.newXhsUserId.value.trim();

  if (!id || !xhsId) {
    el.collectMsg.className = "msg error";
    el.collectMsg.textContent = "账号ID 和 XHS用户ID 不能为空";
    return;
  }

  const accounts = await loadAccounts();
  if (accounts.find((a) => a.account_id === id)) {
    el.collectMsg.className = "msg error";
    el.collectMsg.textContent = "账号ID 已存在";
    return;
  }

  accounts.push({ account_id: id, xhs_user_id: xhsId });
  await saveAccounts(accounts);
  el.newAccountId.value = "";
  el.newXhsUserId.value = "";
  el.collectMsg.textContent = "";
  renderAccountList();
}

async function removeAccount(accountId) {
  let accounts = await loadAccounts();
  accounts = accounts.filter((a) => a.account_id !== accountId);
  await saveAccounts(accounts);
  renderAccountList();
}

function renderAccountList() {
  loadAccounts().then((accounts) => {
    if (accounts.length === 0) {
      el.accountList.innerHTML = '<div class="empty-hint">暂无账号，请添加</div>';
      return;
    }
    el.accountList.innerHTML = accounts
      .map(
        (a) => `
      <div class="account-item">
        <div class="info">
          <div class="id">${esc(a.account_id)}</div>
          <div class="xhs">${esc(a.xhs_user_id)}</div>
        </div>
        <button class="remove" data-id="${esc(a.account_id)}" title="删除">×</button>
      </div>`
      )
      .join("");

    // Bind remove buttons
    el.accountList.querySelectorAll(".remove").forEach((btn) => {
      btn.addEventListener("click", () => removeAccount(btn.dataset.id));
    });
  });
}

// ═══════════════════════════════════════════════════
// Collect
// ═══════════════════════════════════════════════════

async function triggerCollect() {
  el.btnCollect.disabled = true;
  el.btnCollect.textContent = "检查中...";
  el.collectMsg.className = "msg info";
  el.collectMsg.textContent = "正在连接后端...";

  // Check backend
  const online = await checkBackend();
  if (!online) {
    el.collectMsg.className = "msg error";
    el.collectMsg.textContent = "❌ 后端未启动，请先运行 xhs-feishu-server";
    el.btnCollect.disabled = false;
    el.btnCollect.textContent = "🚀 开始";
    return;
  }

  // Check accounts configured
  const { accounts } = await chrome.storage.local.get(["accounts"]);
  if (!accounts || accounts.length === 0) {
    el.collectMsg.className = "msg error";
    el.collectMsg.textContent = "⚠️ 请先在「监控账号」中添加至少一个账号";
    el.btnCollect.disabled = false;
    el.btnCollect.textContent = "🚀 开始";
    return;
  }

  try {
    el.btnCollect.textContent = "采集中...";
    el.collectMsg.textContent = "正在打开小红书创作者中心，采集数据中...（最长等待45秒）";

    // Request Service Worker to trigger collection (may take up to 45s)
    const res = await chrome.runtime.sendMessage({ type: "COLLECT" });

    if (res && res.status === "ok") {
      el.collectMsg.className = "msg success";
      el.collectMsg.textContent = "✅ " + (res.message || "采集完成");
    } else if (res && res.status === "no_data") {
      el.collectMsg.className = "msg error";
      el.collectMsg.textContent = "⚠️ 未采集到数据。请确认已登录小红书创作者中心，且 XHS用户ID 匹配。";
    } else if (res && res.status === "no_accounts") {
      el.collectMsg.className = "msg error";
      el.collectMsg.textContent = "⚠️ 没有配置账号，或没有匹配到有数据的账号";
    } else {
      el.collectMsg.className = "msg error";
      el.collectMsg.textContent = `⚠️ ${res?.error || "采集失败"}`;
    }
  } catch (e) {
    el.collectMsg.className = "msg error";
    el.collectMsg.textContent = `❌ ${e.message}`;
  }

  await updateLastRun();
  el.btnCollect.disabled = false;
  el.btnCollect.textContent = "🚀 开始";
}

async function updateLastRun() {
  // First try chrome.storage (stored by service worker)
  const { lastCollectResult, scheduleInfo } = await chrome.storage.local.get([
    "lastCollectResult",
    "scheduleInfo",
  ]);

  if (lastCollectResult && lastCollectResult.time) {
    const d = new Date(lastCollectResult.time);
    const timeStr =
      d.toLocaleDateString("zh-CN") +
      " " +
      d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
    el.lastRun.textContent = `上次采集: ${timeStr} | 账号: ${lastCollectResult.accounts || 0} | 笔记: ${lastCollectResult.notes || 0}`;

    // Show next scheduled time
    if (scheduleInfo && scheduleInfo.hour !== undefined) {
      el.lastRun.textContent += ` | ⏰ 每日 ${scheduleInfo.hour}:00`;
    }
    return;
  }

  // Fallback: API status
  try {
    const res = await fetch(`${API}/status`);
    const data = await res.json();
    if (data.last_run) {
      el.lastRun.textContent = `上次采集: ${data.last_run} | 笔记: ${data.notes_synced || 0}`;
    }
  } catch {
    // ignore
  }
}

// ═══════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════

function togglePassword() {
  const field = el.appSecret;
  field.type = field.type === "password" ? "text" : "password";
  el.toggleSecret.textContent = field.type === "password" ? "👁" : "🙈";
}

function bindCollapse(headerId, bodyId, toggleId) {
  const header = document.getElementById(headerId);
  const body = document.getElementById(bodyId);
  const toggle = document.getElementById(toggleId);
  header.addEventListener("click", () => {
    body.classList.toggle("collapsed");
    header.classList.toggle("collapsed");
  });
}

function esc(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// Periodic health check
setInterval(checkBackend, 5000);
