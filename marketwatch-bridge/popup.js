const status = document.getElementById("status");

chrome.runtime.sendMessage({ type: "glassbox-status" }, (bridgeStatus) => {
  const state = bridgeStatus?.state || "waiting";
  const detail = bridgeStatus?.detail || "Open settings, then visit the Wolves Portfolio page.";
  status.textContent = `${state}: ${detail}`;
});

document.getElementById("options").addEventListener("click", () => chrome.runtime.openOptionsPage());
