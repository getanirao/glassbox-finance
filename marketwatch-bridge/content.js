(() => {
  if (globalThis.__glassboxBridgeLoaded) return;
  globalThis.__glassboxBridgeLoaded = true;

  const GAME_SLUG = "wolves-of-wall-street---july-2026";
  const parser = globalThis.GlassboxMarketWatchParser;
  let captureTimer;
  let lastStatus = "";

  function isVisible(element) {
    const style = getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden" && element.getClientRects().length > 0;
  }

  function tableContext(table) {
    const parts = [table.getAttribute("aria-label"), table.querySelector("caption")?.textContent];
    let current = table.parentElement;
    for (let depth = 0; current && depth < 4; depth += 1, current = current.parentElement) {
      parts.push(current.getAttribute("aria-label"), current.id);
      const heading = current.querySelector(":scope > h1, :scope > h2, :scope > h3, :scope > h4, :scope > [role='heading']");
      if (heading) parts.push(heading.textContent);
    }
    return parser.clean(parts.filter(Boolean).join(" "));
  }

  function tables() {
    return [...document.querySelectorAll("table")].map((table) => {
      const headerRow = table.querySelector("thead tr") || table.querySelector("tr");
      const headers = headerRow
        ? [...headerRow.querySelectorAll("th, td")].map((cell) => parser.clean(cell.textContent).toLowerCase())
        : [];
      const rows = [...table.rows]
        .filter(row => row.parentElement !== table.tHead)
        .filter(isVisible)
        .map((row) => [...row.querySelectorAll("th, td")].map((cell) => parser.clean(cell.textContent)));
      return { headers, rows, context: tableContext(table), visible: isVisible(table) };
    });
  }

  async function digest(value) {
    const bytes = new TextEncoder().encode(value);
    const hash = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(hash)].map((item) => item.toString(16).padStart(2, "0")).join("");
  }

  async function readActivity(tableModels) {
    const rows = parser.parseActivity(tableModels);
    return Promise.all(rows.map(async ({ stable, ...row }) => ({
      event_id: await digest(stable),
      ...row
    })));
  }

  function statusBadge() {
    let badge = document.getElementById("glassbox-marketwatch-bridge");
    if (!badge) {
      badge = document.createElement("aside");
      badge.id = "glassbox-marketwatch-bridge";
      badge.setAttribute("aria-live", "polite");
      badge.style.cssText = "position:fixed;right:12px;bottom:12px;z-index:2147483647;max-width:280px;padding:9px 12px;border-radius:8px;background:#12251c;color:#f5fbf7;border:1px solid #3f9e6b;font:12px/1.35 ui-monospace,monospace;box-shadow:0 4px 18px #0006";
      document.documentElement.append(badge);
    }
    return badge;
  }

  function updateBadge(status) {
    const text = `Glassbox sync: ${status?.state || "waiting"}${status?.detail ? ` - ${status.detail}` : ""}`;
    if (text !== lastStatus) {
      statusBadge().textContent = text;
      lastStatus = text;
    }
  }

  async function capture() {
    if (!location.pathname.includes(GAME_SLUG)) return;
    const tableModels = tables();
    const snapshot = parser.parsePortfolio(tableModels, document.body?.innerText);
    snapshot.cash_balance = parser.parseCashBalance(document.body?.innerText);
    snapshot.cash_complete = snapshot.cash_balance !== null;
    const payload = {
      schema_version: 1,
      game_slug: GAME_SLUG,
      observed_at: new Date().toISOString(),
      snapshot,
      activity: snapshot.positions_complete && snapshot.cash_complete ? await readActivity(tableModels) : []
    };
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ type: "glassbox-capture", payload }, (status) => {
        const runtimeError = chrome.runtime.lastError;
        if (runtimeError) {
          reject(new Error(runtimeError.message));
          return;
        }
        updateBadge(status);
        resolve(status);
      });
    });
  }

  function scheduleCapture() {
    clearTimeout(captureTimer);
    captureTimer = setTimeout(() => capture().catch((error) => updateBadge({ state: "blocked", detail: String(error) })), 1200);
  }

  new MutationObserver(scheduleCapture).observe(document.documentElement, { childList: true, subtree: true });
  setInterval(scheduleCapture, 20_000);
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "glassbox-capture-now") return false;
    capture().then(
      (status) => sendResponse({ accepted: true, state: status?.state || "pending" }),
      (error) => sendResponse({ accepted: false, detail: String(error?.message || error) }),
    );
    return true;
  });
  chrome.runtime.sendMessage({ type: "glassbox-status" }, updateBadge);
  scheduleCapture();
})();
