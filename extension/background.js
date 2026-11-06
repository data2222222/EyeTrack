// Study Focus Collector: reports the active domain, a sanitized URL path (no query, fragment or
// credentials), the page title, scrolling and idle state to the local engine, and shows the
// focus-mode screen on distracting sites during a study session.
const ENGINE = "http://127.0.0.1:8000";
const IDLE_SECONDS = 60;
const SWITCH_WINDOW_MS = 5 * 60 * 1000;
const SCROLL_WINDOW_MS = 60 * 1000;
const ALLOW_MS = 5 * 60 * 1000;      // "Continue anyway" lasts 5 minutes per site
const MAX_PATH_SEGMENTS = 3;
const MAX_TITLE_CHARS = 200;

const PRODUCTIVE = [
  "github.com", "gitlab.com", "stackoverflow.com", "stackexchange.com", "notion.so",
  "docs.google.com", "drive.google.com", "localhost", "127.0.0.1", "developer.mozilla.org",
  "docs.python.org", "w3schools.com", "leetcode.com", "overleaf.com", "coursera.org",
  "khanacademy.org", "claude.ai", "wolframalpha.com", "desmos.com", "quizlet.com",
];
const DISTRACTION = [
  "youtube.com", "reddit.com", "x.com", "twitter.com", "instagram.com", "facebook.com",
  "tiktok.com", "netflix.com", "twitch.tv", "9gag.com", "pinterest.com",
];
// everything else (google.com, wikipedia.org, ...) is neutral

// short-video feeds: each new video counts as a "swipe"
const FEEDS = [/youtube\.com\/shorts/, /instagram\.com\/(reels?|explore)/, /tiktok\.com/, /facebook\.com\/(reel|watch)/];

const scrollLog = [];   // {t, tabId, px, swipes}  (lives in memory; fine if the worker restarts)
let lastReport = 0;

function matches(domain, list) {
  return list.some((d) => domain === d || domain.endsWith("." + d));
}

function categorize(domain) {
  if (matches(domain, DISTRACTION)) return "distraction";
  if (matches(domain, PRODUCTIVE)) return "productive";
  return "neutral";
}

function domainOf(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== "http:" && u.protocol !== "https:") return u.protocol + u.hostname;
    return u.hostname.replace(/^www\./, "");
  } catch {
    return "unknown";
  }
}

// "youtube.com/watch": host + at most 3 path segments. Query, fragment and credentials never leave.
function sanitizePath(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== "http:" && u.protocol !== "https:") return "";
    const segments = u.pathname.split("/").filter(Boolean).slice(0, MAX_PATH_SEGMENTS);
    return [u.hostname.replace(/^www\./, ""), ...segments].join("/");
  } catch {
    return "";
  }
}

async function recentSwitches(addOne) {
  const now = Date.now();
  const { switches = [] } = await chrome.storage.local.get("switches");
  const recent = switches.filter((t) => now - t < SWITCH_WINDOW_MS);
  if (addOne) recent.push(now);
  await chrome.storage.local.set({ switches: recent });
  return recent.length;
}

function scrollFor(tabId) {
  const now = Date.now();
  while (scrollLog.length && now - scrollLog[0].t > SCROLL_WINDOW_MS) scrollLog.shift();
  let px = 0, swipes = 0;
  for (const s of scrollLog) if (s.tabId === tabId) { px += s.px; swipes += s.swipes; }
  return { px, swipes };
}

async function isAllowed(domain) {
  const { allowUntil = {} } = await chrome.storage.local.get("allowUntil");
  return (allowUntil[domain] || 0) > Date.now();
}

const BADGES = {
  "Focused": ["ON", "#1f7a4d"],
  "Distracted": ["!", "#b3261e"],
  "Doom-scrolling": ["!!", "#8e24aa"],
  "On Phone": ["📱", "#c2185b"],
  "AFK": ["AFK", "#3a3a3a"],
  "Scattered": ["~", "#b26a00"],
};

// The tab's title only belongs to its URL once loading is done and the title has caught up with the
// latest URL change (YouTube and other single-page sites change the URL first, the title later).
// Pages whose title never changes would wait forever, so the wait ends after TITLE_LAG_MS.
const TITLE_LAG_MS = 3000;
const urlChangedAt = new Map();   // tab id -> time of a URL change with no title update since

function freshTitle(tab) {
  if (tab.status !== "complete" || Date.now() - (urlChangedAt.get(tab.id) || 0) < TITLE_LAG_MS) return "";
  const title = (tab.title || "").trim();
  return title && title !== tab.url ? title.slice(0, MAX_TITLE_CHARS) : "";
}

async function report(tabSwitched = false) {
  lastReport = Date.now();
  let domain = "(outside browser)";
  let category = "other";
  let tab = null;
  let scroll = { px: 0, swipes: 0 };
  let feed = false;

  const win = await chrome.windows.getLastFocused().catch(() => null);
  if (win && win.focused) {
    [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    domain = tab && tab.url ? domainOf(tab.url) : "unknown";
    category = categorize(domain);
    if (tab) {
      scroll = scrollFor(tab.id);
      feed = FEEDS.some((re) => re.test(tab.url || ""));
    }
  }

  // incognito tabs: domain/category only, no path or title (the engine never sends them anywhere).
  // A missing title makes the engine wait for the next report instead of judging a bare URL.
  const incognito = !!(tab && tab.incognito);
  const pageInfo = tab && !incognito && category !== "other"
    ? { path: sanitizePath(tab.url || ""), title: freshTitle(tab) }
    : {};

  const payload = {
    domain,
    category,
    incognito,
    ...pageInfo,
    idle: await chrome.idle.queryState(IDLE_SECONDS),
    switches: await recentSwitches(tabSwitched),
    scroll_px: scroll.px,
    swipes: scroll.swipes,
    feed,
    ts: Date.now(),
  };

  try {
    const res = await fetch(ENGINE + "/activity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const status = await res.json();
    const [text, color] = BADGES[status.state] || ["", "#4a5568"];
    chrome.action.setBadgeText({ text });
    chrome.action.setBadgeBackgroundColor({ color });
    chrome.action.setTitle({ title: `Study Focus: ${status.state} (index ${status.index})` });

    // focus mode: cover distracting sites during the work part of a study session. Sent on every
    // report so the screen's clock stays in sync; "unblock" removes it when the block or session ends.
    if (tab) {
      const block = status.block && !(await isAllowed(domain));
      chrome.tabs.sendMessage(tab.id, block ? {
        type: "block", domain, subject: status.subject, goal: status.goal,
        left: status.block_left, total: status.block_total, skips: status.skips,
        source: status.category_source, confidence: status.category_confidence,
      } : { type: "unblock" }).catch(() => {});   // no content script on this page (e.g. opened before install)
    }
  } catch {
    if (tab) chrome.tabs.sendMessage(tab.id, { type: "unblock" }).catch(() => {});   // engine gone: fail open
    chrome.action.setBadgeText({ text: "off" });
    chrome.action.setBadgeBackgroundColor({ color: "#777777" });
    chrome.action.setTitle({ title: "Study Focus: engine not running" });
  }
}

function setup() {
  chrome.idle.setDetectionInterval(IDLE_SECONDS);
  chrome.alarms.create("heartbeat", { periodInMinutes: 0.5 });
  report();
}

chrome.runtime.onInstalled.addListener(setup);
chrome.runtime.onStartup.addListener(setup);
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "heartbeat") report(); });
chrome.tabs.onActivated.addListener(() => report(true));
chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.title) urlChangedAt.delete(tabId);
  else if (info.url) urlChangedAt.set(tabId, Date.now());
  if (tab.active && (info.url || info.title || info.status === "complete")) report();
});
chrome.tabs.onRemoved.addListener((tabId) => urlChangedAt.delete(tabId));
chrome.windows.onFocusChanged.addListener(() => report());
chrome.idle.onStateChanged.addListener(() => report());

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (!msg || !sender.tab) return;
  if (msg.type === "activity") {
    scrollLog.push({ t: Date.now(), tabId: sender.tab.id, px: msg.px || 0, swipes: msg.swipes || 0 });
    if (Date.now() - lastReport > 4000) report();
  } else if (msg.type === "refresh") {
    report();   // the focus screen's clock ran out: ask the engine whether the block is over
  } else if (msg.type === "leave") {
    // back in history; a tab with no history goes to the new-tab page
    const tabId = sender.tab.id;
    chrome.tabs.goBack(tabId).catch(() => chrome.tabs.update(tabId, { url: "chrome://newtab/" }));
  } else if (msg.type === "allow" && msg.domain) {
    chrome.storage.local.get("allowUntil").then(({ allowUntil = {} }) => {
      allowUntil[msg.domain] = Date.now() + ALLOW_MS;
      chrome.storage.local.set({ allowUntil });
    });
    fetch(ENGINE + "/api/override", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domain: msg.domain }),
    }).catch(() => {});
  }
});
