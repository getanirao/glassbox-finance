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
    status.textContent = "Enter a valid bridge endpoint.";
    return;
  }
  const isLoopback = endpoint.hostname === "127.0.0.1" || endpoint.hostname === "localhost";
  const validProtocol = endpoint.protocol === "https:" || (endpoint.protocol === "http:" && isLoopback);
  if (!validProtocol || endpoint.username || endpoint.password || !endpoint.hostname) {
    status.textContent = "Use HTTPS, or HTTP only for localhost / 127.0.0.1.";
    return;
  }
  const token = tokenInput.value.trim();
  if (token.length < 32) {
    status.textContent = "Use a bridge token of at least 32 characters.";
    return;
  }
  if (!isLoopback) {
    const origin = `${endpoint.protocol}//${endpoint.host}/*`;
    const granted = await chrome.permissions.request({ origins: [origin] });
    if (!granted) {
      status.textContent = "The HTTPS host permission is required to sync.";
      return;
    }
  }
  await chrome.storage.local.set({ bridgeConfig: { endpoint: endpoint.origin, token } });
  tokenInput.value = "";
  status.textContent = "Saved. Open the signed-in Wolves Portfolio page to establish the baseline.";
});

load();
