const endpointInput = document.getElementById("endpoint");
const tokenInput = document.getElementById("token");
const status = document.getElementById("status");

async function load() {
  const { bridgeConfig } = await chrome.storage.local.get("bridgeConfig");
  endpointInput.value = bridgeConfig?.endpoint || "";
}

document.getElementById("save").addEventListener("click", async () => {
  let endpoint;
  try {
    endpoint = new URL(endpointInput.value.trim());
  } catch {
    status.textContent = "Enter a valid HTTPS endpoint.";
    return;
  }
  if (endpoint.protocol !== "https:" || endpoint.username || endpoint.password || !endpoint.hostname) {
    status.textContent = "The bridge endpoint must be a plain HTTPS URL.";
    return;
  }
  const token = tokenInput.value.trim();
  if (token.length < 32) {
    status.textContent = "Use a bridge token of at least 32 characters.";
    return;
  }
  const origin = `${endpoint.protocol}//${endpoint.host}/*`;
  const granted = await chrome.permissions.request({ origins: [origin] });
  if (!granted) {
    status.textContent = "The HTTPS host permission is required to sync.";
    return;
  }
  await chrome.storage.local.set({ bridgeConfig: { endpoint: endpoint.origin, token } });
  tokenInput.value = "";
  status.textContent = "Saved. Open the signed-in Wolves Portfolio page to establish the baseline.";
});

load();
