const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const plain = (value) => JSON.parse(JSON.stringify(value));   // objects made in the vm sandbox have foreign prototypes
const backgroundSource = readFileSync(join(__dirname, "..", "background.js"), "utf8");

function createEvent() {
  const listeners = [];
  return {
    addListener(listener) { listeners.push(listener); },
    async emit(...args) {
      assert.equal(listeners.length, 1, "background.js must register its event listener");
      for (const listener of listeners) await listener(...args);
      await new Promise(setImmediate);
    },
  };
}

function createHarness(tabOverrides = {}, { status = { state: "Distracted", index: 1, block: true } } = {}) {
  let now = 1_800_000_000_000;
  let engineAvailable = true;
  const activeTab = {
    id: 7,
    active: true,
    status: "complete",
    incognito: false,
    url: "https://www.youtube.com/watch?v=first",
    title: "First video",
    ...tabOverrides,
  };
  const storage = {};
  const reports = [];
  const messages = [];
  const badgeTexts = [];
  const badgeColors = [];
  const actionTitles = [];
  const ruleUpdates = [];
  const redirected = [];
  let rules = [];
  const chrome = {
    runtime: {
      onInstalled: createEvent(),
      onStartup: createEvent(),
      onMessage: createEvent(),
      getURL(path) { return `chrome-extension://abc/${path}`; },
    },
    declarativeNetRequest: {
      async getDynamicRules() { return rules; },
      async updateDynamicRules({ removeRuleIds, addRules }) {
        ruleUpdates.push({ removeRuleIds, addRules });
        rules = rules.filter(({ id }) => !removeRuleIds.includes(id)).concat(addRules);
      },
    },
    alarms: { create() {}, onAlarm: createEvent() },
    windows: {
      async getLastFocused() { return { focused: true }; },
      onFocusChanged: createEvent(),
    },
    tabs: {
      async query(query) {
        if (query.url) return [{ ...activeTab }];   // blocked-site lookup
        assert.equal(query.active, true);
        assert.equal(query.lastFocusedWindow, true);
        return [{ ...activeTab }];
      },
      async update(tabId, props) { redirected.push({ tabId, ...props }); },
      async sendMessage(tabId, message) {
        messages.push({ tabId, ...structuredClone(message) });
      },
      onActivated: createEvent(),
      onUpdated: createEvent(),
      onRemoved: createEvent(),
    },
    idle: {
      setDetectionInterval() {},
      async queryState(seconds) {
        assert.equal(seconds, 60);
        return "active";
      },
      onStateChanged: createEvent(),
    },
    storage: {
      local: {
        async get(key) { return structuredClone({ [key]: storage[key] }); },
        async set(values) { Object.assign(storage, structuredClone(values)); },
      },
    },
    action: {
      setBadgeText({ text }) { badgeTexts.push(text); },
      setBadgeBackgroundColor({ color }) { badgeColors.push(color); },
      setTitle({ title }) { actionTitles.push(title); },
    },
  };
  class FakeDate extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  }
  vm.runInNewContext(backgroundSource, {
    chrome,
    URL,
    Date: FakeDate,
    async fetch(url, options) {
      assert.equal(url, "http://127.0.0.1:8000/activity");
      assert.equal(options.method, "POST");
      assert.equal(options.headers["Content-Type"], "application/json");
      reports.push(JSON.parse(options.body));
      if (!engineAvailable) throw new Error("Engine unavailable");
      return { async json() { return status; } };
    },
  }, { filename: "background.js" });
  return {
    reports,
    ruleUpdates,
    redirected,
    messages,
    badgeTexts,
    badgeColors,
    actionTitles,
    advance(milliseconds) { now += milliseconds; },
    disconnectEngine() { engineAvailable = false; },
    heartbeat() { return chrome.alarms.onAlarm.emit({ name: "heartbeat" }); },
    async update(changes) {
      Object.assign(activeTab, changes);
      await chrome.tabs.onUpdated.emit(activeTab.id, changes, { ...activeTab });
    },
  };
}

test("SPA navigation suppresses stale titles until the delayed title arrives", async () => {
  const harness = createHarness();
  await harness.heartbeat();
  await harness.update({ url: "https://www.youtube.com/watch?v=second" });
  harness.advance(1000);
  await harness.heartbeat();
  await harness.update({ title: "Second video" });

  assert.deepEqual(harness.reports.map(({ title }) => title), [
    "First video", "", "", "Second video",
  ]);
  assert.ok(harness.reports.every(({ path }) => path === "youtube.com/watch"));
  assert.equal(harness.reports[2].ts - harness.reports[1].ts, 1000);
});

test("loading suppresses even a fresh title until the completion event", async () => {
  const harness = createHarness();
  await harness.update({ url: "https://www.youtube.com/watch?v=second", status: "loading" });
  await harness.update({ title: "Second video" });
  harness.advance(5000);
  await harness.heartbeat();
  await harness.update({ status: "complete" });

  assert.deepEqual(harness.reports.map(({ title }) => title), ["", "", "", "Second video"]);
});

test("an unchanged title becomes usable at the title-lag timeout", async () => {
  const harness = createHarness();
  await harness.update({ url: "https://www.youtube.com/watch?v=second" });
  harness.advance(2999);
  await harness.heartbeat();
  harness.advance(1);
  await harness.heartbeat();

  assert.deepEqual(harness.reports.map(({ title }) => title), ["", "", "First video"]);
});

test("same-URL title changes trigger a new report without a heartbeat", async () => {
  const harness = createHarness();
  await harness.heartbeat();
  await harness.update({ title: "Updated video title" });

  assert.equal(harness.reports.length, 2);
  assert.equal(harness.reports[1].title, "Updated video title");
  assert.equal(harness.reports[1].path, harness.reports[0].path);
  assert.equal(harness.reports[1].switches, 0);
});

test("incognito reports domain/category without title, path, or private URL data", async () => {
  const harness = createHarness({
    incognito: true,
    url: "https://private-user:private-pass@www.github.com/private-repo/issues?private-query#private-fragment",
    title: "private-title",
  });
  await harness.heartbeat();
  await harness.update({ title: "private-updated-title" });

  assert.equal(harness.reports.length, 2);
  for (const payload of harness.reports) {
    assert.equal(payload.domain, "github.com");
    assert.equal(payload.category, "productive");
    assert.equal(payload.incognito, true);
    assert.equal(Object.hasOwn(payload, "path"), false);
    assert.equal(Object.hasOwn(payload, "title"), false);
    assert.doesNotMatch(JSON.stringify(payload), /private-/);
  }
});

const pathCases = [
  {
    name: "HTTPS credentials, query, fragment, and fourth path segment are stripped",
    url: "https://private-user:private-pass@www.github.com/one/two/three/private-four?private-query#private-fragment",
    domain: "github.com", category: "productive", path: "github.com/one/two/three",
  },
  {
    name: "HTTP also strips credentials, port, query, fragment, and extra path segments",
    url: "http://private-user:private-pass@www.example.com:8080/one/two/three/private-four?private-query#private-fragment",
    domain: "example.com", category: "neutral", path: "example.com/one/two/three",
  },
  {
    name: "empty path segments do not consume the three-segment limit",
    url: "https://www.example.com//one///two/three/private-four/",
    domain: "example.com", category: "neutral", path: "example.com/one/two/three",
  },
  {
    name: "root URLs contain only the hostname",
    url: "https://www.example.com/?private-query#private-fragment",
    domain: "example.com", category: "neutral", path: "example.com",
  },
  {
    name: "Chrome internal URLs have no reported path",
    url: "chrome://settings/private-path?private-query#private-fragment",
    domain: "chrome:settings", category: "neutral", path: "",
  },
  {
    name: "local file URLs have no reported path",
    url: "file:///home/private-user/private-file?private-query#private-fragment",
    domain: "file:", category: "neutral", path: "",
  },
  {
    name: "malformed URLs have no reported path",
    url: "not a URL private-path?private-query#private-fragment",
    domain: "unknown", category: "neutral", path: "",
  },
];

for (const { name, url, domain, category, path } of pathCases) {
  test(name, async () => {
    const harness = createHarness({ url, title: "Public page title" });
    await harness.heartbeat();

    assert.equal(harness.reports.length, 1);
    const [payload] = harness.reports;
    assert.equal(payload.domain, domain);
    assert.equal(payload.category, category);
    assert.equal(payload.path, path);
    assert.equal(payload.incognito, false);
    assert.equal(payload.title, "Public page title");
    assert.doesNotMatch(JSON.stringify(payload), /private-/);
  });
}

test("page titles are trimmed and limited to 200 characters", async () => {
  const harness = createHarness({ title: `  ${"Long title ".repeat(30)}  ` });
  await harness.heartbeat();

  assert.equal(harness.reports[0].title, "Long title ".repeat(30).trim().slice(0, 200));
});

test("a title equal to the raw URL is suppressed rather than leaking query data", async () => {
  const url = "https://example.com/page?private-query#private-fragment";
  const harness = createHarness({ url, title: url });
  await harness.heartbeat();

  assert.equal(harness.reports[0].title, "");
  assert.doesNotMatch(JSON.stringify(harness.reports[0]), /private-/);
});

test("engine unavailability clears an existing block and marks the badge off", async () => {
  const harness = createHarness();
  await harness.heartbeat();
  assert.equal(harness.messages[0].type, "block");
  harness.disconnectEngine();
  await harness.heartbeat();

  assert.equal(harness.reports.length, 2);
  assert.deepEqual(harness.messages[1], { tabId: 7, type: "unblock" });
  assert.equal(harness.badgeTexts.at(-1), "off");
  assert.equal(harness.badgeColors.at(-1), "#777777");
  assert.equal(harness.actionTitles.at(-1), "Study Focus: engine not running");
});

test("blocked sites become redirect rules once, and open tabs on them are redirected", async () => {
  const status = { state: "Focused", index: 0, blocked_sites: ["reddit.com", "youtube.com"] };
  const harness = createHarness({}, { status });
  await harness.heartbeat();
  await harness.heartbeat();   // same list: rules are not rebuilt

  assert.equal(harness.ruleUpdates.length, 1);
  const [{ addRules }] = harness.ruleUpdates;
  assert.deepEqual(plain(addRules.map((rule) => rule.condition.requestDomains)), [["reddit.com"], ["youtube.com"]]);
  assert.ok(addRules.every((rule) => rule.condition.resourceTypes.join() === "main_frame"));
  assert.equal(addRules[0].action.redirect.extensionPath, "/blocked.html#reddit.com");
  assert.ok(harness.redirected.some(({ tabId, url }) => tabId === 7 && url === "chrome-extension://abc/blocked.html#youtube.com"));

  status.blocked_sites = [];
  await harness.heartbeat();
  assert.deepEqual(plain(harness.ruleUpdates[1].addRules), []);
  assert.deepEqual(plain(harness.ruleUpdates[1].removeRuleIds), [1, 2]);
});

test("replies without a blocked-site list and malformed hosts leave the rules alone", async () => {
  const status = { state: "Focused", index: 0, blocked_sites: ["bad host", 5, "*.evil"] };
  const harness = createHarness({}, { status });
  await harness.heartbeat();
  assert.deepEqual(plain(harness.ruleUpdates[0].addRules), []);
  delete status.blocked_sites;
  await harness.heartbeat();
  assert.equal(harness.ruleUpdates.length, 1);
});
