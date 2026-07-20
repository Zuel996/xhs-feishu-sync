/**
 * xhs-feishu-sync — Content Script
 *
 * 注入到 creator.xiaohongshu.com 页面，拦截 XHS API 响应数据。
 * XHS 使用 Service Worker 通信模式：页面 ↔ SW ↔ 网络。
 * 不走 window.fetch/XMLHttpRequest，而是通过 postMessage 通道。
 *
 * 拦截策略（三层）：
 *   1. SW postMessage 通道 — 页面 ↔ Service Worker（主力）
 *   2. BroadcastChannel — 跨上下文广播（备用）
 *   3. fetch / XMLHttpRequest — 传统 HTTP（兜底）
 *
 * 拦截的 API:
 *   - personal_info          → 账号 Profile (粉丝/关注/获赞)
 *   - note/analyze           → 笔记互动数据 (浏览/点赞/收藏/评论/分享)
 *   - note_detail_new        → 笔记列表 + 7/30天趋势汇总
 */

// ── 全局标记，防止重复注入 ──
if (window.__XHS_INTERCEPTOR_LOADED__) {
  console.log("[xhs-feishu-sync] ⚠️ Already loaded, skipping duplicate injection");
} else {
  window.__XHS_INTERCEPTOR_LOADED__ = true;
}

// ── 缓存最近拦截到的 API 响应 ──
let cachedProfile = null;
let cachedNotes = [];
const HOOKED_APIS = [
  "personal_info",
  "datacenter/note/analyze",
  "note_detail_new",
];

// ═══════════════════════════════════════════════════
// 🔍 诊断模块
// ═══════════════════════════════════════════════════

const DIAG = {
  scriptLoadTime: Date.now(),
  swController: null,
  swRegistrations: [],
  swRegisterHooked: false,
  swPostMessageSent: 0,
  swMessageReceived: 0,
  broadcastSent: 0,
  broadcastReceived: 0,
  windowPostMessage: 0,
  fetchCalled: 0,
  xhrCalled: 0,
  sendBeaconHooked: false,
  hooksStillInPlace: null,
  fetchToString: "",
  xhrToString: "",
  // 最深扫描到的数据结构（帮助理解消息格式）
  lastSwMsgShape: "",
  lastBroadcastMsgShape: "",
  lastWindowMsgShape: "",
  // SW 消息样本（前几条）
  swMsgSamples: [],
};

// ── 持久化诊断数据 ──
function saveDiagnostics() {
  chrome.storage?.local?.set({ xhs_diagnostics: DIAG }).catch(() => {});
  window.__XHS_DIAG__ = DIAG;
}

// ── 检测 Service Worker ──
if ("serviceWorker" in navigator) {
  DIAG.swController = !!navigator.serviceWorker.controller;
  console.log("[xhs-feishu-sync] 🔍 ServiceWorker.controller:", DIAG.swController);

  navigator.serviceWorker.getRegistrations().then((regs) => {
    DIAG.swRegistrations = regs.map((r) => ({
      scope: r.scope,
      active: r.active ? r.active.scriptURL : null,
    }));
    console.log("[xhs-feishu-sync] 🔍 Registered SW:", JSON.stringify(DIAG.swRegistrations));
    saveDiagnostics();
  }).catch((e) => {
    console.log("[xhs-feishu-sync] 🔍 SW getRegistrations error:", e.message);
  });

  // Hook register()
  if (navigator.serviceWorker.register) {
    const origRegister = navigator.serviceWorker.register.bind(navigator.serviceWorker);
    navigator.serviceWorker.register = function (scriptURL, options) {
      DIAG.swRegisterHooked = true;
      console.log("[xhs-feishu-sync] 🔍 SW.register() called:", scriptURL);
      return origRegister(scriptURL, options);
    };
  }
}

// ── 检测 sendBeacon ──
if (navigator.sendBeacon) {
  DIAG.sendBeaconHooked = true;
  const origSendBeacon = navigator.sendBeacon.bind(navigator);
  navigator.sendBeacon = function (url, data) {
    console.log("[xhs-feishu-sync] 🔍 sendBeacon URL:", url);
    return origSendBeacon(url, data);
  };
}

// ═══════════════════════════════════════════════════
// 🎯 主力拦截：SW postMessage 通道
// ═══════════════════════════════════════════════════

function hookSWPostMessage() {
  // 出站 hook 是否已安装成功（初始 + 延迟共享状态）
  let swPostMessageHooked = false;

  // 安装出站 hook 的通用函数
  function installPostMessageHook(label) {
    if (!navigator.serviceWorker.controller || !navigator.serviceWorker.controller.postMessage) return false;
    const origPostMsg = navigator.serviceWorker.controller.postMessage.bind(
      navigator.serviceWorker.controller
    );
    navigator.serviceWorker.controller.postMessage = function (message, transfer) {
      DIAG.swPostMessageSent++;
      try {
        const preview = JSON.stringify(message).substring(0, 300);
        console.log("[xhs-feishu-sync] 🔍 Page→SW" + label + ":", preview);
        if (DIAG.swMsgSamples.length < 5) {
          DIAG.swMsgSamples.push({ dir: "out", shape: describeShape(message), preview });
        }
        DIAG.lastSwMsgShape = describeShape(message);
        scanForApiData(message);
      } catch (_) { /* ignore */ }
      saveDiagnostics();
      return origPostMsg(message, transfer);
    };
    return true;
  }

  // ── 1. Hook 出站：页面 → SW（立即尝试）──
  if (navigator.serviceWorker.controller && navigator.serviceWorker.controller.postMessage) {
    try {
      swPostMessageHooked = installPostMessageHook("");
      if (swPostMessageHooked) {
        console.log("[xhs-feishu-sync] ✅ SW postMessage hook installed (outgoing)");
      }
    } catch (e) {
      console.log("[xhs-feishu-sync] ⚠️ Failed to hook SW postMessage:", e.message);
    }
  } else {
    console.log("[xhs-feishu-sync] ⚠️ No SW controller for postMessage hook at document_start, will retry");
  }

  // ── 2. Hook 入站：SW → 页面（直接监听 message 事件）──
  navigator.serviceWorker.addEventListener("message", (event) => {
    DIAG.swMessageReceived++;
    try {
      const data = event.data;
      const preview = JSON.stringify(data).substring(0, 300);
      console.log("[xhs-feishu-sync] 🔍 SW→Page:", preview);
      if (DIAG.swMsgSamples.length < 5) {
        DIAG.swMsgSamples.push({ dir: "in", shape: describeShape(data), preview });
      }
      DIAG.lastSwMsgShape = describeShape(data);
      scanForApiData(data);
      saveDiagnostics();
    } catch (_) { /* ignore */ }
  });
  console.log("[xhs-feishu-sync] ✅ SW message listener installed (incoming)");

  // ── 3. 延迟 hook：等 SW controller 可用 ──
  // 某些场景下 SW controller 在 document_start 时尚未激活
  let hookAttempts = 0;
  const delayedHook = setInterval(() => {
    hookAttempts++;
    if (navigator.serviceWorker.controller) {
      DIAG.swController = true;
      if (!swPostMessageHooked) {
        try {
          swPostMessageHooked = installPostMessageHook(" (delayed)");
          if (swPostMessageHooked) {
            console.log("[xhs-feishu-sync] ✅ SW postMessage hook installed (delayed) after", hookAttempts * 500, "ms");
          }
        } catch (e) {
          console.log("[xhs-feishu-sync] ⚠️ Failed to hook SW postMessage (delayed):", e.message);
        }
      }
    }
    if (swPostMessageHooked || hookAttempts > 20) {
      clearInterval(delayedHook);
      if (!swPostMessageHooked) {
        console.log("[xhs-feishu-sync] ⚠️ SW postMessage hook never installed after", hookAttempts * 500, "ms");
      }
    }
  }, 500);
}

// ═══════════════════════════════════════════════════
// 🎯 备用拦截：BroadcastChannel
// ═══════════════════════════════════════════════════

function hookBroadcastChannel() {
  try {
    const OrigBroadcastChannel = window.BroadcastChannel;
    if (!OrigBroadcastChannel) return;

    window.BroadcastChannel = function (name) {
      const channel = new OrigBroadcastChannel(name);
      console.log("[xhs-feishu-sync] 🔍 BroadcastChannel created:", name);

      // Hook postMessage
      const origPostMsg = channel.postMessage.bind(channel);
      channel.postMessage = function (message) {
        DIAG.broadcastSent++;
        try {
          const preview = JSON.stringify(message).substring(0, 200);
          console.log("[xhs-feishu-sync] 🔍 BroadcastChannel.send:", name, preview);
          scanForApiData(message);
        } catch (_) { /* ignore */ }
        saveDiagnostics();
        return origPostMsg(message);
      };

      // Hook incoming
      const origAddEventListener = channel.addEventListener.bind(channel);
      channel.addEventListener = function (type, listener, options) {
        if (type === "message") {
          const wrapped = function (event) {
            DIAG.broadcastReceived++;
            try {
              const preview = JSON.stringify(event.data).substring(0, 200);
              console.log("[xhs-feishu-sync] 🔍 BroadcastChannel.recv:", name, preview);
              DIAG.lastBroadcastMsgShape = describeShape(event.data);
              scanForApiData(event.data);
            } catch (_) { /* ignore */ }
            saveDiagnostics();
            return listener.call(this, event);
          };
          return origAddEventListener(type, wrapped, options);
        }
        return origAddEventListener(type, listener, options);
      };

      return channel;
    };
    window.BroadcastChannel.prototype = OrigBroadcastChannel.prototype;
    console.log("[xhs-feishu-sync] ✅ BroadcastChannel hook installed");
  } catch (e) {
    console.log("[xhs-feishu-sync] ⚠️ Failed to hook BroadcastChannel:", e.message);
  }
}

// ═══════════════════════════════════════════════════
// 🎯 备用拦截：window.postMessage
// ═══════════════════════════════════════════════════

function hookWindowPostMessage() {
  window.addEventListener("message", (event) => {
    // 忽略扩展自身的消息
    if (event.source === window) return;
    DIAG.windowPostMessage++;
    try {
      const data = event.data;
      if (data && typeof data === "object") {
        const preview = JSON.stringify(data).substring(0, 200);
        console.log("[xhs-feishu-sync] 🔍 window.postMessage:", preview);
        DIAG.lastWindowMsgShape = describeShape(data);
        scanForApiData(data);
        saveDiagnostics();
      }
    } catch (_) { /* ignore */ }
  });
  console.log("[xhs-feishu-sync] ✅ window.postMessage listener installed");
}

// ═══════════════════════════════════════════════════
// 🎯 兜底拦截：fetch + XHR（保留，以防万一）
// ═══════════════════════════════════════════════════

const originalFetch = window.fetch;
window.fetch = async function (...args) {
  DIAG.fetchCalled++;
  const response = await originalFetch.apply(this, args);
  try {
    const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
    if (isTargetApi(url)) {
      const cloned = response.clone();
      const text = await cloned.text();
      try {
        const data = JSON.parse(text);
        processApiResponse(url, data);
      } catch (_) { /* Not JSON */ }
    }
  } catch (_) { /* ignore */ }
  return response;
};

const OriginalXHR = window.XMLHttpRequest;
window.XMLHttpRequest = function () {
  const xhr = new OriginalXHR();
  const originalOpen = xhr.open;
  let _url = "";
  xhr.open = function (method, url, ...rest) {
    _url = typeof url === "string" ? url : url?.toString() || "";
    DIAG.xhrCalled++;
    return originalOpen.call(this, method, url, ...rest);
  };
  const originalSend = xhr.send;
  xhr.send = function (...sendArgs) {
    xhr.addEventListener("load", function () {
      if (!isTargetApi(_url)) return;
      try {
        const data = JSON.parse(xhr.responseText);
        processApiResponse(_url, data);
      } catch (_) { /* Not JSON */ }
    });
    return originalSend.apply(this, sendArgs);
  };
  return xhr;
};
window.XMLHttpRequest.prototype = OriginalXHR.prototype;

// ── 捕获签名用于存活检测 ──
DIAG.fetchToString = window.fetch.toString().substring(0, 200);
DIAG.xhrToString = window.XMLHttpRequest.toString().substring(0, 200);

// ═══════════════════════════════════════════════════
// API 匹配 + 数据处理
// ═══════════════════════════════════════════════════

function isTargetApi(url) {
  if (!url.includes("api/galaxy")) return false;
  for (const key of HOOKED_APIS) {
    if (url.includes(key)) return true;
  }
  return false;
}

/** 递归扫描数据中的 XHS API 响应 */
function scanForApiData(data, depth) {
  if (!data || typeof data !== "object") return;
  if (depth === undefined) depth = 0;
  if (depth > 5) return; // 防止深层递归

  // ── 检查是否包含 API URL ──
  if (typeof data.url === "string" && isTargetApi(data.url)) {
    console.log("[xhs-feishu-sync] 🎯 Found API URL in message:", data.url);
  }

  // ── 检查是否包含 XHS API 响应体 ──
  // XHS 响应特征: {code: 0, success: true, data: { ... }}
  if (data.code !== undefined && (data.code === 0 || data.code === "0")) {
    if (data.data && typeof data.data === "object") {
      console.log("[xhs-feishu-sync] 🎯 Found XHS API response in message!");
      processApiData(data.data);
      return;
    }
  }

  // ── 检查嵌套数据（某些字段直接是 XHS 数据）──
  if (data.fans_count || data.red_id || data.name) {
    console.log("[xhs-feishu-sync] 🎯 Found profile-like data in message");
    cachedProfile = extractProfile({ data });
    return;
  }
  if (data.note_id || data.note_infos || data.notes) {
    console.log("[xhs-feishu-sync] 🎯 Found note-like data in message");
    const notes = extractNotes({ data });
    if (notes.length > 0) mergeNotes(notes);
    return;
  }

  // ── 递归扫描 ──
  if (Array.isArray(data)) {
    for (const item of data) {
      scanForApiData(item, depth + 1);
    }
  } else {
    for (const key of Object.keys(data)) {
      const val = data[key];
      if (val && typeof val === "object") {
        scanForApiData(val, depth + 1);
      }
      // 也检查字符串类型的 URL
      if (typeof val === "string" && isTargetApi(val)) {
        console.log("[xhs-feishu-sync] 🎯 Found API URL string in message:", val);
      }
    }
  }
}

/** 处理通过 SW 通道传来的 API 数据 */
function processApiData(inner) {
  // 检测是否为 profile 数据
  if (inner.fans_count || inner.red_id || inner.name || inner.fansCount || inner.redId) {
    const profile = extractProfile({ data: inner });
    if (profile) {
      cachedProfile = profile;
      console.log("[xhs-feishu-sync] ✅ Profile captured via SW:", profile.follower_count, "fans");
    }
  }

  // 检测是否为笔记数据
  const notes = extractNotes({ data: inner });
  if (notes.length > 0) {
    mergeNotes(notes);
    console.log("[xhs-feishu-sync] ✅ Notes captured via SW:", notes.length, "new, total:", cachedNotes.length);
  }

  // 递归扫描 inner 的嵌套字段
  for (const key of Object.keys(inner)) {
    const val = inner[key];
    if (val && typeof val === "object" && !Array.isArray(val)) {
      processApiData(val);
    }
  }
}

function processApiResponse(url, data) {
  // fetch/XHR 兜底路径
  if (data.code !== undefined && data.code !== 0 && data.code !== "0") return;
  const inner = data.data || data;
  processApiData(inner);
}

function mergeNotes(notes) {
  const existingIds = new Set(cachedNotes.map((n) => n.note_id));
  for (const note of notes) {
    if (!existingIds.has(note.note_id)) {
      cachedNotes.push(note);
      existingIds.add(note.note_id);
    }
  }
}

// ═══════════════════════════════════════════════════
// Profile extraction
// ═══════════════════════════════════════════════════

function extractProfile(data) {
  const result = data.data || data;
  if (!result.red_id && !result.name && !result.fans_count && !result.fansCount) return null;
  return {
    account_id: "",
    xhs_user_id: result.red_id || result.xhs_user_id || "",
    username: result.name || result.nickname || "",
    follower_count: safeInt(result.fans_count) || safeInt(result.fansCount) || 0,
    following_count: safeInt(result.follow_count) || safeInt(result.followCount) || 0,
    total_likes: safeInt(result.faved_count) || safeInt(result.favedCount) || 0,
    total_collections: 0,
    competitor: false,
  };
}

// ═══════════════════════════════════════════════════
// Note extraction
// ═══════════════════════════════════════════════════

function extractNotes(data) {
  const inner = data.data || data;
  const notes = [];
  let noteList =
    inner.note_infos || inner.noteInfos || inner.notes ||
    inner.note_list || inner.noteList || inner.list ||
    inner.items || inner.note_detail || inner.noteDetail || [];

  if (!noteList.length && typeof inner === "object") {
    for (const key of Object.keys(inner)) {
      const val = inner[key];
      if (Array.isArray(val) && val.length > 0 && typeof val[0] === "object") {
        const first = val[0];
        if (first.note_id || first.id || first.title || first.read_count || first.view_count) {
          noteList = val;
          break;
        }
      }
    }
  }

  for (const item of noteList) {
    if (typeof item !== "object" || !item) continue;
    const noteId = item.note_id || item.noteId || item.id || "";
    if (!noteId) continue;
    const stats = item.interact_info || item.interactInfo || item.note_stat || item.noteStat || item;
    notes.push({
      note_id: String(noteId),
      account_id: "",
      title: item.title || item.display_title || item.displayTitle || "",
      note_type: safeNoteType(item.type || item.note_type || item.noteType),
      publish_date: parsePublishDate(item.post_time || item.publish_time || item.time || item.create_time),
      url: item.url || item.note_url || item.noteUrl || `https://www.xiaohongshu.com/explore/${noteId}`,
      views: safeInt(stats.read_count || stats.readCount || stats.view_count || stats.viewCount || item.view_count || item.viewCount || 0),
      likes: safeInt(stats.like_count || stats.likeCount || stats.liked_count || stats.likedCount || 0),
      favorites: safeInt(stats.fav_count || stats.favCount || stats.collect_count || stats.collectCount || stats.collected_count || stats.collectedCount || 0),
      comments: safeInt(stats.comment_count || stats.commentCount || 0),
      shares: safeInt(stats.share_count || stats.shareCount || 0),
      impressions: safeInt(stats.imp_count || stats.impCount || item.imp_count || item.impCount || 0),
      ctr: 0, new_followers: 0, avg_watch_time: 0, danmaku: 0, sort_order: 0,
    });
  }
  return notes;
}

// ═══════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════

function safeInt(val) {
  if (val === null || val === undefined || val === "") return 0;
  const n = parseInt(val, 10);
  return isNaN(n) ? 0 : n;
}

function safeNoteType(val) {
  if (val === 1 || val === "1" || val === "image") return "image";
  if (val === 2 || val === "2" || val === "video") return "video";
  return String(val || "image");
}

function parsePublishDate(val) {
  if (!val) return null;
  if (typeof val === "number") {
    const d = new Date(val < 1e12 ? val * 1000 : val);
    return d.toISOString().slice(0, 10);
  }
  if (typeof val === "string") {
    if (val.includes("T")) return val.slice(0, 10);
    if (/^\d{4}-\d{2}-\d{2}$/.test(val)) return val;
  }
  return null;
}

/** 描述消息的数据结构 */
function describeShape(obj) {
  if (obj === null) return "null";
  if (Array.isArray(obj)) return `array[${obj.length}]`;
  if (typeof obj !== "object") return typeof obj;
  const keys = Object.keys(obj).slice(0, 8);
  const summary = keys.map((k) => {
    const v = obj[k];
    if (v === null) return `${k}:null`;
    if (Array.isArray(v)) return `${k}:array`;
    return `${k}:${typeof v}`;
  }).join(", ");
  return `{${summary}}${Object.keys(obj).length > 8 ? "..." : ""}`;
}

// ═══════════════════════════════════════════════════
// 初始化 — 安装所有 Hook
// ═══════════════════════════════════════════════════

hookSWPostMessage();
hookBroadcastChannel();
hookWindowPostMessage();

// ── 定期检查 hooks 存活状态 ──
setInterval(() => {
  const currentFetchStr = window.fetch.toString().substring(0, 100);
  const currentXhrStr = window.XMLHttpRequest.toString().substring(0, 100);
  DIAG.hooksStillInPlace = {
    fetch: currentFetchStr === DIAG.fetchToString.substring(0, 100),
    xhr: currentXhrStr === DIAG.xhrToString.substring(0, 100),
    fetchCalls: DIAG.fetchCalled,
    xhrCalls: DIAG.xhrCalled,
    swPostMsgOut: DIAG.swPostMessageSent,
    swPostMsgIn: DIAG.swMessageReceived,
    broadcastOut: DIAG.broadcastSent,
    broadcastIn: DIAG.broadcastReceived,
    windowPostMsg: DIAG.windowPostMessage,
  };
  saveDiagnostics();
}, 5000);

setTimeout(saveDiagnostics, 1000);
setTimeout(saveDiagnostics, 5000);

// ═══════════════════════════════════════════════════
// Message handler — respond to Service Worker
// ═══════════════════════════════════════════════════

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "COLLECT_DATA") {
    sendResponse({
      account_id: "",
      profile: cachedProfile,
      notes: [...cachedNotes],
    });
  }
  if (message.type === "GET_DIAGNOSTICS") {
    saveDiagnostics();
    sendResponse(DIAG);
  }
  return true;
});

console.log("[xhs-feishu-sync] Content script loaded — SW/Fetch/XHR/BroadcastChannel hooks active");
