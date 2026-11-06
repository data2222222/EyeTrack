// Study Focus Collector: reports the active domain (never the full URL) to the local engine.
const ENGINE_URL = "http://127.0.0.1:8000/activity";
const IDLE_SECONDS = 60;
const SWITCH_WINDOW_MS = 5 * 60 * 1000;

const PRODUCTIVE = [
  "github.com", "gitlab.com", "stackoverflow.com", "stackexchange.com", "notion.so",
  "docs.google.com", "drive.google.com", "localhost", "127.0.0.1", "developer.mozilla.org",
  "docs.python.org", "w3schools.com", "leetcode.com", "overleaf.com", "coursera.org",
  "khanacademy.org", "claude.ai",
];
const DISTRACTION = [
  "youtube.com", "reddit.com", "x.com", "twitter.com", "instagram.com", "facebook.com",
  "tiktok.com", "netflix.com", "twitch.tv", "9gag.com",
];
// everything else (google.com, wikipedia.org, ...) is neutral

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

async function recentSwitches(addOne) {
  const now = Date.now();
  const { switches = [] } = await chrome.storage.local.get("switches");
  const recent = switches.filter((t) => now - t < SWITCH_WINDOW_MS);
  if (addOne) recent.push(now);
  await chrome.storage.local.set({ switches: recent });
  return recent.length;
}

const BADGES = {
  "Focused": ["ON", "#1f7a4d"],
  "Distracted": ["!", "#b3261e"],
  "AFK": ["AFK", "#3a3a3a"],
  "Scattered": ["~", "#b26a00"],
};

async function report(tabSwitched = false) {
  let domain = "(outside browser)";
  let category = "other";

  const win = await chrome.windows.getLastFocused().catch(() => null);
  if (win && win.focused) {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    domain = tab && tab.url ? domainOf(tab.url) : "unknown";
    category = categorize(domain);
  }

  const payload = {
    domain,
    category,
    idle: await chrome.idle.queryState(IDLE_SECONDS),
    switches: await recentSwitches(tabSwitched),
    ts: Date.now(),
  };

  try {
    const res = await fetch(ENGINE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const status = await res.json();
    const [text, color] = BADGES[status.state] || ["", "#4a5568"];
    chrome.action.setBadgeText({ text });
    chrome.action.setBadgeBackgroundColor({ color });
    chrome.action.setTitle({ title: `Study Focus: ${status.state} (index ${status.index})` });
  } catch {
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
  if (tab.active && (info.url || info.status === "complete")) report();
});
chrome.windows.onFocusChanged.addListener(() => report());
chrome.idle.onStateChanged.addListener(() => report());
