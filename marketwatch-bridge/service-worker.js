const DB_NAME = "glassbox-marketwatch-bridge";
const STORE_NAME = "outbox";
const SYNC_ALARM = "glassbox-sync";
const GAME_SLUG = "wolves-of-wall-street---july-2026";
const MAX_RETRY_DELAY_MS = 30 * 60 * 1000;
const HEARTBEAT_INTERVAL_MS = 60 * 1000;

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
  if (!payload.snapshot?.cash_complete || !Number.isFinite(payload.snapshot?.cash_balance)) {
    await setStatus({ state: "waiting", detail: "Waiting for the visible Cash Remaining value before syncing." });
    return { accepted: false, state: "waiting" };
  }
  const hash = stableSnapshotHash(payload);
  const now = Date.now();
  const { lastSnapshotHash, lastSnapshotQueuedAt, bridgeStatus } = await chrome.storage.local.get([
    "lastSnapshotHash", "lastSnapshotQueuedAt", "bridgeStatus"
  ]);
  if (hash === lastSnapshotHash && now - Number(lastSnapshotQueuedAt || 0) < HEARTBEAT_INTERVAL_MS) {
    return {
      accepted: true,
      state: bridgeStatus?.state || "unchanged",
      detail: bridgeStatus?.detail
    };
  }
  await enqueue(payload);
  await chrome.storage.local.set({ lastSnapshotHash: hash, lastSnapshotQueuedAt: now });
  await setStatus({ state: "pending", detail: "Portfolio snapshot queued for reconciliation." });
  await flushOutbox();
  const { bridgeStatus: updatedStatus } = await chrome.storage.local.get("bridgeStatus");
  return {
    accepted: true,
    state: updatedStatus?.state || "pending",
    detail: updatedStatus?.detail
  };
}

function isWolvesTab(tab) {
  return typeof tab?.id === "number" && tab.url?.includes(`/games/${GAME_SLUG}`);
}

async function requestCaptureFromTab(tab) {
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "glassbox-capture-now" });
    return true;
  } catch (error) {
    const detail = String(error?.message || error);
    if (!detail.includes("Receiving end does not exist")) {
      throw error;
    }
    // Reloading an unpacked extension disconnects old content scripts until the page reloads.
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["parser-core.js", "content.js"] });
    return true;
  }
}

async function requestPortfolioCapture() {
  const tabs = await chrome.tabs.query({ url: "https://www.marketwatch.com/games/*" });
  const wolvesTabs = tabs.filter(isWolvesTab);
  if (!wolvesTabs.length) {
    await setStatus({ state: "waiting", detail: "Keep the signed-in Wolves Portfolio page open for heartbeat sync." });
    return false;
  }
  const results = await Promise.allSettled(wolvesTabs.map(requestCaptureFromTab));
  const failure = results.find((result) => result.status === "rejected");
  if (failure) {
    await setStatus({ state: "pending", detail: String(failure.reason?.message || failure.reason) });
    return false;
  }
  return true;
}

async function runScheduledSync() {
  try {
    await requestPortfolioCapture();
    await flushOutbox();
  } catch (error) {
    await setStatus({ state: "pending", detail: String(error?.message || error) });
  }
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
    runScheduledSync();
  }
});
chrome.alarms.create(SYNC_ALARM, { periodInMinutes: 1 });
chrome.runtime.onInstalled.addListener(() => runScheduledSync());
chrome.runtime.onStartup.addListener(() => runScheduledSync());
