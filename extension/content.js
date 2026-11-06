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
  let overlay = null;

  function showOverlay(msg) {
    if (overlay) return;
    document.querySelectorAll("video, audio").forEach((m) => { try { m.pause(); } catch {} });

    overlay = document.createElement("div");
    overlay.style.cssText = "position:fixed;inset:0;z-index:2147483647;";
    const root = overlay.attachShadow({ mode: "closed" });
    root.innerHTML = `
      <style>
        .bg { position:fixed; inset:0; background:rgba(12,14,18,.94); display:flex;
              align-items:center; justify-content:center; font-family:system-ui,sans-serif; }
        .card { background:#1f2226; color:#f2f2f2; border-radius:18px; padding:36px 40px;
                max-width:460px; text-align:center; box-shadow:0 20px 60px rgba(0,0,0,.5); }
        .tag { display:inline-block; background:#1f7a4d; color:#fff; border-radius:99px;
               padding:4px 12px; font-size:12px; letter-spacing:.05em; text-transform:uppercase; }
        h1 { font-size:26px; margin:16px 0 8px; }
        p { color:#b8bec6; line-height:1.5; margin:6px 0; }
        .goal { color:#fff; font-weight:600; }
        .row { display:flex; gap:12px; justify-content:center; margin-top:24px; }
        button { border:0; border-radius:10px; padding:12px 18px; font-size:15px; cursor:pointer; }
        .primary { background:#1f7a4d; color:#fff; font-weight:600; }
        .secondary { background:#2b2f34; color:#9aa0a6; }
        .secondary:disabled { cursor:not-allowed; opacity:.6; }
      </style>
      <div class="bg"><div class="card">
        <span class="tag">Focus mode</span>
        <h1>You're in a study session</h1>
        <p>Subject: <span class="goal" id="subject"></span></p>
        <p id="goalLine">Your goal: <span class="goal" id="goal"></span></p>
        <p><span id="domain"></span> is on your distraction list.</p>
        <div class="row">
          <button class="primary" id="back">Back to studying</button>
          <button class="secondary" id="cont" disabled>Continue anyway (10)</button>
        </div>
      </div></div>`;
    root.getElementById("subject").textContent = msg.subject || "Study";
    root.getElementById("goal").textContent = msg.goal || "";
    if (!msg.goal) root.getElementById("goalLine").style.display = "none";
    root.getElementById("domain").textContent = msg.domain || "This site";

    const cont = root.getElementById("cont");
    let left = 10;
    const countdown = setInterval(() => {
      left -= 1;
      if (left <= 0) {
        clearInterval(countdown);
        cont.disabled = false;
        cont.textContent = "Continue anyway (5 min)";
      } else {
        cont.textContent = `Continue anyway (${left})`;
      }
    }, 1000);

    root.getElementById("back").onclick = () => {
      chrome.runtime.sendMessage({ type: "leave" }).catch(() => {});
    };
    cont.onclick = () => {
      chrome.runtime.sendMessage({ type: "allow", domain: msg.domain }).catch(() => {});
      clearInterval(countdown);
      overlay.remove();
      overlay = null;
    };
    document.documentElement.appendChild(overlay);
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg && msg.type === "block") showOverlay(msg);
    if (msg && msg.type === "unblock" && overlay) { overlay.remove(); overlay = null; }
  });
})();
