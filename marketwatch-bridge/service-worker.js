const DB_NAME = "glassbox-marketwatch-bridge";
const STORE_NAME = "outbox";
const SYNC_ALARM = "glassbox-sync";
const GAME_SLUG = "wolves-of-wall-street---july-2026";
const MAX_RETRY_DELAY_MS = 30 * 60 * 1000;

function openDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      const store = request.result.createObjectStore(STORE_NAME, { keyPath: "id" });
      store.createIndex("nextAttemptAt", "nextAttemptAt");
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore(mode, callback) {
  const database = await openDatabase();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, mode);
      const result = callback(transaction.objectStore(STORE_NAME));
      transaction.oncomplete = () => resolve(result);
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally {
    database.close();
  }
}

async function getDueEvents() {
  const now = Date.now();
  return withStore("readonly", (store) => new Promise((resolve, reject) => {
    const request = store.getAll();
    request.onsuccess = () => resolve(request.result.filter((event) => event.nextAttemptAt <= now));
    request.onerror = () => reject(request.error);
  }));
}

async function enqueue(payload) {
  const event = {
    id: crypto.randomUUID(),
    payload,
    attempts: 0,
    nextAttemptAt: Date.now(),
    queuedAt: new Date().toISOString()
  };
  await withStore("readwrite", (store) => store.put(event));
  return event;
}

async function deleteEvent(id) {
  await withStore("readwrite", (store) => store.delete(id));
}

async function deferEvent(event, detail) {
  event.attempts += 1;
  const delay = Math.min(MAX_RETRY_DELAY_MS, 15_000 * (2 ** Math.min(event.attempts, 10)));
  event.nextAttemptAt = Date.now() + delay;
  event.lastError = detail;
  await withStore("readwrite", (store) => store.put(event));
}

async function setStatus(status) {
  await chrome.storage.local.set({ bridgeStatus: { ...status, updatedAt: new Date().toISOString() } });
}

async function configuredBridge() {
  const { bridgeConfig } = await chrome.storage.local.get("bridgeConfig");
  if (!bridgeConfig?.endpoint || !bridgeConfig?.token) {
    return null;
  }
  return bridgeConfig;
}

async function flushOutbox() {
  const config = await configuredBridge();
  if (!config) {
    await setStatus({ state: "needs_configuration", detail: "Open extension options to configure HTTPS endpoint and token." });
    return;
  }
  const events = await getDueEvents();
  for (const event of events) {
    try {
      const response = await fetch(`${config.endpoint}/v1/marketwatch/snapshot`, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${config.token}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify(event.payload)
      });
      const body = await response.json().catch(() => ({}));
      if (response.ok && body.accepted) {
        await deleteEvent(event.id);
        await setStatus({ state: "healthy", detail: `Acknowledged ${body.imported || 0} new trade(s).` });
      } else if (response.status >= 400 && response.status < 500 && response.status !== 429) {
        // A reconciliation block is durable server state; keeping this payload would only retry a bad snapshot forever.
        await deleteEvent(event.id);
        await setStatus({ state: "blocked", detail: body.detail || `Receiver rejected the snapshot (${response.status}).` });
      } else {
        await deferEvent(event, body.detail || `Receiver unavailable (${response.status}).`);
        await setStatus({ state: "pending", detail: body.detail || "Will retry automatically." });
      }
    } catch (error) {
      await deferEvent(event, String(error));
      await setStatus({ state: "pending", detail: "Network unavailable; snapshot remains in the encrypted browser profile outbox." });
    }
  }
}

function stableSnapshotHash(payload) {
  const snapshot = payload.snapshot;
  const activity = [...payload.activity].sort((a, b) => a.event_id.localeCompare(b.event_id));
  return JSON.stringify({ game_slug: payload.game_slug, snapshot, activity });
}

async function capture(payload, sender) {
  if (!sender.tab?.url?.startsWith("https://www.marketwatch.com/games/") || payload.game_slug !== GAME_SLUG) {
    throw new Error("Rejected a capture outside the configured Wolves game.");
  }
  if (!payload.snapshot?.positions_complete) {
    await setStatus({ state: "waiting", detail: "Open the signed-in Portfolio view so the bridge can read a complete holdings table." });
    return { accepted: false, state: "waiting" };
  }
  const hash = stableSnapshotHash(payload);
  const { lastSnapshotHash } = await chrome.storage.local.get("lastSnapshotHash");
  if (hash === lastSnapshotHash) {
    return { accepted: true, state: "unchanged" };
  }
  await enqueue(payload);
  await chrome.storage.local.set({ lastSnapshotHash: hash });
  await setStatus({ state: "pending", detail: "Portfolio snapshot queued for reconciliation." });
  await flushOutbox();
  return { accepted: true, state: "queued" };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "glassbox-capture") {
    capture(message.payload, sender).then(sendResponse).catch(async (error) => {
      await setStatus({ state: "blocked", detail: String(error.message || error) });
      sendResponse({ accepted: false, state: "blocked" });
    });
    return true;
  }
  if (message?.type === "glassbox-status") {
    chrome.storage.local.get("bridgeStatus").then(({ bridgeStatus }) => sendResponse(bridgeStatus || { state: "waiting" }));
    return true;
  }
  return false;
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === SYNC_ALARM) {
    flushOutbox();
  }
});
chrome.runtime.onInstalled.addListener(() => chrome.alarms.create(SYNC_ALARM, { periodInMinutes: 1 }));
chrome.runtime.onStartup.addListener(() => flushOutbox());
