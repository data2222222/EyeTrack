// Page shown instead of a fully blocked site (see syncBlocklist in background.js).
const host = decodeURIComponent(location.hash.slice(1));
if (/^[a-z0-9.-]+$/i.test(host)) document.getElementById("host").textContent = host;
document.getElementById("back").addEventListener("click", () => {
  if (history.length > 1) history.back();
  else chrome.tabs.update({ url: "chrome://newtab/" });
});
