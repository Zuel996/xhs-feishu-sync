/**
 * xhs-feishu-sync — Content Script
 *
 * 注入到 creator.xiaohongshu.com 页面，拦截 XHS API 响应数据。
 * 无需 CDP 端口 — 直接在页面内通过 hook fetch/XHR 获取数据。
 *
 * 拦截的 API:
 *   - personal_info          → 账号 Profile (粉丝/关注/获赞)
 *   - note/analyze/list      → 笔记互动数据 (浏览/点赞/收藏/评论/分享)
 *   - note_detail_new        → 笔记列表 + 7/30天趋势汇总
 */

// ── 缓存最近拦截到的 API 响应 ──
let cachedProfile = null;
let cachedNotes = [];
const HOOKED_APIS = [
  "personal_info",
  "datacenter/note/analyze",
  "note_detail_new",
];

// ═══════════════════════════════════════════════════
// Hook fetch()
// ═══════════════════════════════════════════════════

const originalFetch = window.fetch;

window.fetch = async function (...args) {
  const response = await originalFetch.apply(this, args);

  try {
    const url = typeof args[0] === "string" ? args[0] : args[0]?.url || "";
    // 🔍 诊断日志：显示所有 fetch 请求 URL（排查完删）
    console.log("[xhs-feishu-sync] 🔍 fetch URL:", url);

    if (isTargetApi(url)) {
      // Clone response so we can read the body
      const cloned = response.clone();
      const text = await cloned.text();
      try {
        const data = JSON.parse(text);
        processApiResponse(url, data);
      } catch (_) {
        // Not JSON — ignore
      }
    }
  } catch (_) {
    // Silently ignore errors
  }

  return response;
};

// ═══════════════════════════════════════════════════
// Hook XMLHttpRequest
// ═══════════════════════════════════════════════════

const OriginalXHR = window.XMLHttpRequest;

window.XMLHttpRequest = function () {
  const xhr = new OriginalXHR();
  const originalOpen = xhr.open;
  let _url = "";

  xhr.open = function (method, url, ...rest) {
    _url = typeof url === "string" ? url : url?.toString() || "";
    return originalOpen.call(this, method, url, ...rest);
  };

  const originalSend = xhr.send;
  xhr.send = function (...sendArgs) {
    xhr.addEventListener("load", function () {
      // 🔍 诊断日志：显示所有 XHR 请求 URL（排查完删）
      console.log("[xhs-feishu-sync] 🔍 XHR URL:", _url);
      if (!isTargetApi(_url)) return;
      try {
        const data = JSON.parse(xhr.responseText);
        processApiResponse(_url, data);
      } catch (_) {
        // Not JSON — ignore
      }
    });
    return originalSend.apply(this, sendArgs);
  };

  return xhr;
};

window.XMLHttpRequest.prototype = OriginalXHR.prototype;

// ═══════════════════════════════════════════════════
// API matching
// ═══════════════════════════════════════════════════

function isTargetApi(url) {
  if (!url.includes("api/galaxy")) return false;
  for (const key of HOOKED_APIS) {
    if (url.includes(key)) return true;
  }
  return false;
}

function processApiResponse(url, data) {
  // XHS API standard wrapper: {code: 0, success: true, data: {...}}
  if (data.code !== undefined && data.code !== 0 && data.code !== "0") return;

  const inner = data.data || data;

  if (url.includes("personal_info")) {
    cachedProfile = extractProfile(inner);
    console.log("[xhs-feishu-sync] Profile captured:", cachedProfile?.follower_count, "fans");
  }

  if (url.includes("note/analyze") || url.includes("note_detail_new")) {
    const notes = extractNotes(inner);
    if (notes.length > 0) {
      // Merge: deduplicate by note_id
      const existingIds = new Set(cachedNotes.map((n) => n.note_id));
      for (const note of notes) {
        if (!existingIds.has(note.note_id)) {
          cachedNotes.push(note);
          existingIds.add(note.note_id);
        }
      }
      console.log("[xhs-feishu-sync] Notes captured:", notes.length, "new, total:", cachedNotes.length);
    }
  }
}

// ═══════════════════════════════════════════════════
// Profile extraction (personal_info)
// ═══════════════════════════════════════════════════

function extractProfile(data) {
  const result = data.data || data;

  if (!result.red_num && !result.name && !result.fans_count) return null;

  return {
    account_id: "", // filled by Service Worker
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
// Note extraction (note/analyze/list + note_detail_new)
// ═══════════════════════════════════════════════════

function extractNotes(data) {
  const inner = data.data || data;
  const notes = [];

  // ── Find the note list ──
  let noteList =
    inner.note_infos ||
    inner.noteInfos ||
    inner.notes ||
    inner.note_list ||
    inner.noteList ||
    inner.list ||
    inner.items ||
    inner.note_detail ||
    inner.noteDetail ||
    [];

  // Try harder: scan inner for an array of note-like objects
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

    // Stats: try interact_info, then item itself
    const stats = item.interact_info || item.interactInfo || item.note_stat || item.noteStat || item;

    notes.push({
      note_id: String(noteId),
      account_id: "", // filled by Service Worker
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
      ctr: 0,
      new_followers: 0,
      avg_watch_time: 0,
      danmaku: 0,
      sort_order: 0,
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
  // Could be millisecond timestamp or ISO string
  if (typeof val === "number") {
    const d = new Date(val < 1e12 ? val * 1000 : val);
    return d.toISOString().slice(0, 10);
  }
  if (typeof val === "string") {
    // ISO string
    if (val.includes("T")) return val.slice(0, 10);
    // Already date string
    if (/^\d{4}-\d{2}-\d{2}$/.test(val)) return val;
  }
  return null;
}

// ═══════════════════════════════════════════════════
// Message handler — respond to Service Worker
// ═══════════════════════════════════════════════════

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "COLLECT_DATA") {
    // Return cached data + clear cache
    const result = {
      account_id: "", // filled by Service Worker from config
      profile: cachedProfile,
      notes: [...cachedNotes],
    };

    // Don't clear cache — data may be requested again
    // (but clear after a delay to avoid stale data)

    sendResponse(result);
  }
  return true;
});

console.log("[xhs-feishu-sync] Content script loaded — API interception active");
