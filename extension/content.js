// Study Focus content script: measures scrolling (for doom-scroll detection) and shows the
// focus-mode screen on distracting sites during a study session. Sends numbers only, never page content.
(() => {
  if (window.__studyFocus) return;
  window.__studyFocus = true;

  let px = 0;          // scrolled pixels since the last report
  let swipes = 0;      // new videos/posts opened in a feed (URL changes)
  let lastUrl = location.href;
  let lastTouchY = null;

  addEventListener("wheel", (e) => {
    const factor = e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? 800 : 1;
    px += Math.abs(e.deltaY) * factor;
  }, { passive: true, capture: true });

  addEventListener("keydown", (e) => {
    const step = { ArrowDown: 60, ArrowUp: 60, PageDown: 700, PageUp: 700, " ": 700, j: 700, k: 700 }[e.key];
    if (step && !/input|textarea|select/i.test(e.target.tagName)) px += step;
  }, { capture: true });

  addEventListener("touchstart", (e) => { lastTouchY = e.touches[0].clientY; }, { passive: true });
  addEventListener("touchmove", (e) => {
    const y = e.touches[0].clientY;
    if (lastTouchY !== null) px += Math.abs(y - lastTouchY);
    lastTouchY = y;
  }, { passive: true });

  const timer = setInterval(() => {
    if (location.href !== lastUrl) {   // Shorts / Reels / TikTok change the URL per video
      lastUrl = location.href;
      swipes += 1;
    }
  }, 1000);

  const report = setInterval(() => {
    if (document.visibilityState !== "visible") return;
    try {
      chrome.runtime.sendMessage({ type: "activity", px: Math.round(px), swipes }).catch(() => {});
    } catch {
      clearInterval(report);           // extension was reloaded: stop this old copy
      clearInterval(timer);
      return;
    }
    px = 0;
    swipes = 0;
  }, 5000);

  // ---------- focus-mode screen ----------
  // Full-page screen over a distracting site during a work block: time left in the block, the goal,
  // why the site was blocked, "Back to studying" and "Give me 5 min" (unlocks after WAIT seconds).
  // background.js re-sends "block" on every report (keeps the clock in sync) and "unblock" when done.
  const WAIT = 10;
  let screen = null;   // { host, root, els, domain, endAt, total, wait, asked, tick, prevOverflow }

  const STYLE = `
    :host { all: initial; }
    .bg { position:fixed; inset:0; background:rgba(14,17,19,.97); display:flex; align-items:center;
          justify-content:center; padding:24px; box-sizing:border-box; color:#e9eef0;
          font:14px/1.5 Inter, system-ui, -apple-system, "Segoe UI", sans-serif; }
    .col { width:min(520px,100%); text-align:center; }
    .mono { font-family:"JetBrains Mono", ui-monospace, "Cascadia Mono", Consolas, monospace; }
    .eyebrow { font-size:11px; font-weight:600; letter-spacing:.12em; text-transform:uppercase; color:#8c99a0; }
    .clock { font-size:clamp(56px,11vw,104px); font-weight:500; line-height:1; letter-spacing:-.04em;
             margin:18px 0 6px; font-variant-numeric:tabular-nums; }
    .muted { color:#8c99a0; font-size:13px; }
    .track { height:4px; background:#283035; border-radius:2px; margin:18px auto 0; width:70%; overflow:hidden; }
    .track i { display:block; height:100%; width:0; background:#4fd1a5; }
    .goal { font-size:19px; font-weight:600; margin:28px 0 6px; text-wrap:balance; overflow-wrap:anywhere; }
    .why { font-size:12px; color:#8c99a0; }
    .why b { color:#e9eef0; font-weight:500; }
    .src { font-size:11px; padding:2px 6px; border:1px solid #283035; border-radius:6px; margin-left:4px; }
    .row { display:flex; gap:10px; justify-content:center; margin-top:26px; flex-wrap:wrap; }
    button { font:600 14px Inter, system-ui, sans-serif; border-radius:12px; padding:12px 20px; cursor:pointer;
             border:1px solid #283035; background:#1e2428; color:#e9eef0; }
    button:hover { background:#283036; }
    .primary { background:#4fd1a5; border-color:#4fd1a5; color:#07140e; }
    .primary:hover { background:#6be0b8; }
    button:disabled { color:#5b676e; background:#14181a; border-color:#20272b; cursor:not-allowed; }
    button:focus-visible { outline:2px solid #4fd1a5; outline-offset:2px; }
    .foot { margin-top:22px; }
    [hidden] { display:none; }`;

  const HTML = `
    <div class="bg" role="dialog" aria-modal="true" aria-labelledby="clock" aria-describedby="goal">
      <div class="col">
        <div class="eyebrow mono" id="subject"></div>
        <div class="clock mono" id="clock" role="timer"></div>
        <div class="muted">left in this focus block</div>
        <div class="track"><i id="bar"></i></div>
        <div class="goal" id="goal"></div>
        <div class="why"><b id="domain"></b> <span id="reason"></span><span class="src mono" id="src"></span></div>
        <div class="row">
          <button class="primary" id="back">Back to studying</button>
          <button id="skip" disabled></button>
        </div>
        <div class="why foot" id="skips"></div>
      </div>
    </div>`;

  // "Jev 0.97" / "Jev, cached" / "site list": who decided this site is a distraction.
  function sourceLabel(source, confidence) {
    if (source === "jev") return typeof confidence === "number" ? `Jev ${confidence.toFixed(2)}` : "Jev";
    if (source === "cache") return "Jev, cached";
    if (source === "override") return "your override";
    return "site list";
  }

  const clockText = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  const timesText = (n) => (n === 1 ? "once" : n === 2 ? "twice" : `${n} times`);

  // Keys, wheel and touch must not reach the page under the screen (YouTube's k / space / arrows).
  // Only Tab (kept inside the screen) and Enter/space on our own buttons do anything.
  function guard(e) {
    if (!screen) return;
    e.stopImmediatePropagation();
    if (e.type === "keydown" && e.key === "Tab") {
      e.preventDefault();
      const order = [screen.els.back, screen.els.skip].filter((b) => !b.disabled);
      const i = order.indexOf(screen.root.activeElement);
      order[(i + (e.shiftKey ? order.length - 1 : 1)) % order.length].focus();
      return;
    }
    const onOurButton = e.target === screen.host && (e.key === "Enter" || e.key === " ");
    if (!onOurButton && e.cancelable) e.preventDefault();
  }
  const GUARDED = ["keydown", "keyup", "keypress", "wheel", "touchmove"];

  // Media that starts again under the screen (autoplay, next video) is paused again.
  function pauseMedia(e) {
    if (screen && e.target instanceof HTMLMediaElement) e.target.pause();
  }

  function render() {
    const left = Math.max(0, Math.round((screen.endAt - Date.now()) / 1000));
    const { els, total } = screen;
    els.clock.textContent = clockText(left);
    els.bar.style.width = total > 0 ? `${Math.min(100, (1 - left / total) * 100)}%` : "0";
    if (screen.wait > 0) {
      els.skip.disabled = true;
      els.skip.textContent = `Give me 5 min · ${screen.wait}`;
    } else if (els.skip.disabled) {
      els.skip.disabled = false;
      els.skip.textContent = "Give me 5 min";
    }
    return left;
  }

  function update(msg) {
    const { els } = screen;
    screen.endAt = Date.now() + Math.max(0, Number(msg.left) || 0) * 1000;
    screen.total = Number(msg.total) || 0;
    screen.domain = msg.domain;
    screen.asked = false;
    const named = msg.subject && msg.subject !== "Focus session";   // engine's default when there's no subject
    els.subject.textContent = named ? `${msg.subject} · focus block` : "Focus block";
    els.goal.textContent = msg.goal || "Stay with it until the timer ends";
    els.domain.textContent = msg.domain || "This site";
    const list = !msg.source || msg.source === "list" || msg.source === "private";
    els.reason.textContent = list ? "is on your distraction list" : "doesn't fit this goal";
    els.src.textContent = sourceLabel(msg.source, msg.confidence);
    els.skips.hidden = !msg.skips;
    els.skips.textContent = msg.skips ? `Skipped ${timesText(msg.skips)} this session` : "";
    render();
  }

  function show(msg) {
    if (screen) return update(msg);
    document.querySelectorAll("video, audio").forEach((m) => { try { m.pause(); } catch {} });

    const host = document.createElement("div");
    host.style.cssText = "position:fixed;inset:0;z-index:2147483647;";
    const root = host.attachShadow({ mode: "closed" });
    root.innerHTML = `<style>${STYLE}</style>${HTML}`;
    const els = Object.fromEntries(
      ["subject", "clock", "bar", "goal", "domain", "reason", "src", "back", "skip", "skips"]
        .map((id) => [id, root.getElementById(id)]));

    screen = { host, root, els, domain: "", endAt: 0, total: 0, wait: WAIT, asked: false,
               prevOverflow: document.documentElement.style.overflow };
    update(msg);
    screen.tick = setInterval(() => {
      if (screen.wait > 0) screen.wait -= 1;
      if (render() === 0 && !screen.asked) {
        screen.asked = true;
        send({ type: "refresh" });   // block over? background answers with "unblock"
      }
    }, 1000);

    els.back.onclick = () => send({ type: "leave" });
    els.skip.onclick = () => { send({ type: "allow", domain: screen.domain }); hide(); };

    GUARDED.forEach((t) => addEventListener(t, guard, { capture: true, passive: false }));
    document.addEventListener("play", pauseMedia, true);
    document.documentElement.style.overflow = "hidden";
    document.documentElement.appendChild(host);
    els.back.focus();
  }

  function hide() {
    if (!screen) return;
    clearInterval(screen.tick);
    GUARDED.forEach((t) => removeEventListener(t, guard, { capture: true }));
    document.removeEventListener("play", pauseMedia, true);
    document.documentElement.style.overflow = screen.prevOverflow;
    screen.host.remove();
    screen = null;
  }

  function send(msg) {
    try { chrome.runtime.sendMessage(msg).catch(() => {}); } catch { hide(); }   // extension reloaded
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === "block") show(msg);
    if (msg && msg.type === "unblock") hide();
  });
})();
