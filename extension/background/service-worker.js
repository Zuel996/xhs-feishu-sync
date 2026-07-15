/**
 * xhs-feishu-sync — Service Worker
 *
 * 职责：
 * - 接收 popup 的"开始"指令 → 自动打开 XHS → 采集 → 通知
 * - 管理 alarm 定时采集
 * - 缓存未发送的数据（离线重试）
 */

const API = "http://localhost:9527";
const COLLECT_TIMEOUT_MS = 45000; // 等待数据超时（给用户时间登录）
const POLL_INTERVAL_MS = 2000;    // 轮询 Content Script 间隔

// ═══════════════════════════════════════════════════
// Install / Startup
// ═══════════════════════════════════════════════════

chrome.runtime.onInstalled.addListener(async () => {
  console.log("[xhs-feishu-sync] Extension installed");

  // 读取用户配置的采集时间（默认 10:00）
  const { scheduleHour } = await chrome.storage.local.get(["scheduleHour"]);
  const hour = scheduleHour || 10;

  // 计算距离下一次采集的分钟数
  const now = new Date();
  const next = new Date(now);
  next.setHours(hour, 0, 0, 0);
  if (next <= now) next.setDate(next.getDate() + 1);
  const delayMinutes = Math.round((next - now) / 60000);

  chrome.alarms.create("daily-check", {
    delayInMinutes: delayMinutes,
    periodInMinutes: 1440,
  });

  console.log(`[xhs-feishu-sync] Daily collect scheduled at ${hour}:00, first in ${delayMinutes} min`);

  // 保存定时信息到 storage
  await chrome.storage.local.set({
    scheduleInfo: { hour, nextRun: next.toISOString() },
  });
});

chrome.runtime.onStartup.addListener(() => {
  checkBackend();
  // 更新下次采集时间
  updateScheduleInfo();
});

// ═══════════════════════════════════════════════════
// Message handler (from popup)
// ═══════════════════════════════════════════════════

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "COLLECT") {
    handleCollect()
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ status: "error", error: err.message }));
    return true; // keep channel open for async response
  }
});

// ═══════════════════════════════════════════════════
// Alarm handler
// ═══════════════════════════════════════════════════

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "daily-check") {
    handleCollect().catch((err) =>
      console.error("[xhs-feishu-sync] Daily collect failed:", err)
    );
  }
});

// ═══════════════════════════════════════════════════
// Core: "开始" 按钮 — 自动打开 XHS → 采集 → 同步
// ═══════════════════════════════════════════════════

async function handleCollect() {
  // 1. Check backend is running
  const backendOk = await checkBackend();
  if (!backendOk) {
    return { status: "error", error: "后端未启动 — 请确保 xhs-feishu-server 在运行" };
  }

  // 2. Check config exists
  const { feishu } = await chrome.storage.local.get(["feishu"]);
  if (!feishu || !feishu.app_id) {
    return { status: "error", error: "飞书未配置 — 请先在插件弹窗中配置飞书凭证" };
  }

  // 3. Send config to backend
  await fetch(`${API}/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(feishu),
  });

  // 4. Load configured accounts
  const { accounts } = await chrome.storage.local.get(["accounts"]);
  if (!accounts || accounts.length === 0) {
    return { status: "no_accounts", error: "没有配置监控账号。请在插件弹窗中添加。" };
  }

  // 5. Find or open XHS creator page
  let tabs = await chrome.tabs.query({
    url: "*://creator.xiaohongshu.com/*",
  });

  let openedTab = null;
  if (tabs.length === 0) {
    // 自动打开 XHS 创作者中心
    openedTab = await chrome.tabs.create({
      url: "https://creator.xiaohongshu.com/",
      active: true,
    });
    tabs = [openedTab];
  } else {
    // 定位到已有标签页
    await chrome.tabs.update(tabs[0].id, { active: true });
  }

  // 6. Wait for Content Script to collect data (poll with timeout)
  const collectedResults = await waitForData(tabs, accounts);

  // 7. If no data after timeout
  if (collectedResults.length === 0) {
    return {
      status: "no_data",
      error:
        "未采集到数据。请确认：" +
        (openedTab ? "1) 已登录小红书创作者中心 " : "") +
        "2) 插件中配置的 XHS用户ID 与登录账号一致。",
    };
  }

  // 8. Send collected data to Python backend
  const syncResults = [];
  for (const { profile, notes, matchedAccount } of collectedResults) {
    try {
      const payload = {
        account_id: matchedAccount.account_id,
        profile: profile,
        notes: notes,
      };

      const backendRes = await fetch(`${API}/collect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (backendRes.ok) {
        const data = await backendRes.json();
        syncResults.push({
          account_id: matchedAccount.account_id,
          notes_synced: data.notes_synced || 0,
        });
      } else {
        const errData = await backendRes.json().catch(() => ({}));
        console.error("[xhs-feishu-sync] Backend error:", errData.detail || backendRes.status);
      }
    } catch (e) {
      console.error(
        "[xhs-feishu-sync] Sync failed for",
        matchedAccount.account_id,
        ":",
        e
      );
    }
  }

  if (syncResults.length === 0) {
    return {
      status: "sync_failed",
      error: "数据已采集但同步失败。请检查后端日志。",
    };
  }

  // 9. Notify user
  const totalNotes = syncResults.reduce((s, r) => s + r.notes_synced, 0);
  const msg = `采集完成: ${syncResults.length} 账号, ${totalNotes} 笔记`;

  chrome.notifications?.create({
    type: "basic",
    iconUrl: "icons/icon-128.png",
    title: "xhs-feishu-sync",
    message: msg,
  });

  // Store result in chrome.storage for popup display
  await chrome.storage.local.set({
    lastCollectResult: {
      time: new Date().toISOString(),
      accounts: syncResults.length,
      notes: totalNotes,
      status: "ok",
    },
  });

  return { status: "ok", message: msg, details: syncResults };
}

// ═══════════════════════════════════════════════════
// Wait for Content Script data (poll with timeout)
// ═══════════════════════════════════════════════════

async function waitForData(tabs, accounts) {
  const startTime = Date.now();
  const results = [];
  const seenTabs = new Set();

  while (Date.now() - startTime < COLLECT_TIMEOUT_MS) {
    // Re-query XHS tabs (user might have navigated)
    const currentTabs = await chrome.tabs.query({
      url: "*://creator.xiaohongshu.com/*",
    });

    for (const tab of currentTabs) {
      if (seenTabs.has(tab.id)) continue; // already collected from this tab

      try {
        const collected = await chrome.tabs.sendMessage(tab.id, {
          type: "COLLECT_DATA",
        });

        if (!collected || !collected.profile) continue;

        const { profile, notes } = collected;

        // Match profile to configured account by xhs_user_id
        const matchedAccount = accounts.find(
          (a) => a.xhs_user_id === profile.xhs_user_id
        );

        if (!matchedAccount) {
          console.log(
            "[xhs-feishu-sync] Profile xhs_user_id=" +
              profile.xhs_user_id +
              " not in configured accounts:",
            accounts.map((a) => a.xhs_user_id)
          );
          continue;
        }

        // Only collect if we have notes data too
        if (notes.length === 0) continue;

        // Fill in account_id from config
        profile.account_id = matchedAccount.account_id;
        notes.forEach((n) => (n.account_id = matchedAccount.account_id));

        results.push({ profile, notes, matchedAccount });
        seenTabs.add(tab.id);

        console.log(
          "[xhs-feishu-sync] Data collected from tab",
          tab.id,
          ":",
          notes.length,
          "notes"
        );
      } catch (e) {
        // Content script may not be ready yet — ignore and retry
      }
    }

    // If we got results, return immediately
    if (results.length > 0) break;

    // Wait before next poll
    await sleep(POLL_INTERVAL_MS);
  }

  return results;
}

// ═══════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════

async function checkBackend() {
  try {
    const res = await fetch(`${API}/health`);
    return res.ok;
  } catch {
    return false;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function updateScheduleInfo() {
  const alarms = await chrome.alarms.getAll();
  const dailyAlarm = alarms.find((a) => a.name === "daily-check");
  if (dailyAlarm) {
    await chrome.storage.local.set({
      scheduleInfo: {
        hour: new Date(dailyAlarm.scheduledTime).getHours(),
        nextRun: new Date(dailyAlarm.scheduledTime).toISOString(),
      },
    });
  }
}
