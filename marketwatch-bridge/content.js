const GAME_SLUG = "wolves-of-wall-street---july-2026";
let captureTimer;
let lastStatus = "";

function clean(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function numberFrom(value) {
  const normalized = clean(value).replace(/[$,%]/g, "").replace(/,/g, "");
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function integerFrom(value) {
  const parsed = numberFrom(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function headerIndex(headers, names) {
  return headers.findIndex((header) => names.some((name) => header.includes(name)));
}

function tables() {
  return [...document.querySelectorAll("table")].map((table) => {
    const headerRow = table.querySelector("thead tr") || table.querySelector("tr");
    const headers = headerRow ? [...headerRow.querySelectorAll("th, td")].map((cell) => clean(cell.textContent).toLowerCase()) : [];
    const rows = [...table.querySelectorAll("tbody tr")].map((row) => [...row.querySelectorAll("th, td")].map((cell) => clean(cell.textContent)));
    return { headers, rows };
  });
}

function readPortfolio() {
  for (const table of tables()) {
    const tickerIndex = headerIndex(table.headers, ["ticker", "symbol"]);
    const sharesIndex = headerIndex(table.headers, ["shares", "quantity", "qty"]);
    if (tickerIndex < 0 || sharesIndex < 0) continue;
    const positions = [];
    for (const row of table.rows) {
      const ticker = clean(row[tickerIndex]).toUpperCase();
      const shares = integerFrom(row[sharesIndex]);
      if (/^[A-Z.]{1,8}$/.test(ticker) && shares) positions.push({ ticker, shares });
    }
    return { positions_complete: true, positions };
  }
  const pageText = clean(document.body?.innerText).toLowerCase();
  if (pageText.includes("your portfolio") && pageText.includes("you currently have no holdings")) {
    return { positions_complete: true, positions: [] };
  }
  return { positions_complete: false, positions: [] };
}

function readCashBalance() {
  const text = clean(document.body?.innerText);
  const match = text.match(/cash(?:\s+balance)?\s*[:$]?\s*\$?([\d,]+(?:\.\d{2})?)/i);
  return match ? numberFrom(match[1]) : null;
}

function partsInZone(date) {
  const values = {};
  for (const part of new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23"
  }).formatToParts(date)) {
    if (part.type !== "literal") values[part.type] = Number(part.value);
  }
  return values;
}

function easternTimestamp(value) {
  const text = clean(value);
  const match = text.match(/(?:([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})|(\d{1,2})\/(\d{1,2})\/(\d{4})).*?(\d{1,2}):(\d{2})\s*(AM|PM)/i);
  if (!match) return null;
  const months = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
  const month = match[1] ? months[match[1].slice(0, 3).toLowerCase()] : Number(match[4]);
  const day = Number(match[2] || match[5]);
  const year = Number(match[3] || match[6]);
  let hour = Number(match[7]);
  const minute = Number(match[8]);
  if (match[9].toUpperCase() === "PM" && hour !== 12) hour += 12;
  if (match[9].toUpperCase() === "AM" && hour === 12) hour = 0;
  if (!month || !day || !year) return null;
  const target = Date.UTC(year, month - 1, day, hour, minute);
  let guess = target;
  for (let i = 0; i < 3; i += 1) {
    const current = partsInZone(new Date(guess));
    const displayed = Date.UTC(current.year, current.month - 1, current.day, current.hour, current.minute);
    guess += target - displayed;
  }
  return new Date(guess).toISOString();
}

async function digest(value) {
  const bytes = new TextEncoder().encode(value);
  const hash = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(hash)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

async function readActivity() {
  const activity = [];
  for (const table of tables()) {
    const tickerIndex = headerIndex(table.headers, ["ticker", "symbol"]);
    const actionIndex = headerIndex(table.headers, ["action", "type", "order"]);
    const sharesIndex = headerIndex(table.headers, ["shares", "quantity", "qty"]);
    const priceIndex = headerIndex(table.headers, ["price", "fill"]);
    const timeIndex = headerIndex(table.headers, ["date", "time", "executed"]);
    if ([tickerIndex, actionIndex, sharesIndex, priceIndex, timeIndex].some((index) => index < 0)) continue;
    for (const row of table.rows) {
      const ticker = clean(row[tickerIndex]).toUpperCase();
      const actionMatch = clean(row[actionIndex]).match(/\b(buy|sell)\b/i);
      const shares = integerFrom(row[sharesIndex]);
      const price = numberFrom(row[priceIndex]);
      const executedAt = easternTimestamp(row[timeIndex]);
      if (!/^[A-Z.]{1,8}$/.test(ticker) || !actionMatch || !shares || !price || !executedAt) continue;
      const stable = JSON.stringify({ ticker, action: actionMatch[1].toLowerCase(), shares, price, executedAt });
      activity.push({ event_id: await digest(stable), ticker, action: actionMatch[1].toLowerCase(), shares, price, executed_at: executedAt });
    }
  }
  return activity;
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
  const text = `Glassbox sync: ${status?.state || "waiting"}${status?.detail ? ` — ${status.detail}` : ""}`;
  if (text !== lastStatus) {
    statusBadge().textContent = text;
    lastStatus = text;
  }
}

async function capture() {
  if (!location.pathname.includes(GAME_SLUG)) return;
  const snapshot = readPortfolio();
  snapshot.cash_balance = readCashBalance();
  const payload = {
    schema_version: 1,
    game_slug: GAME_SLUG,
    observed_at: new Date().toISOString(),
    snapshot,
    activity: snapshot.positions_complete ? await readActivity() : []
  };
  chrome.runtime.sendMessage({ type: "glassbox-capture", payload }, updateBadge);
}

function scheduleCapture() {
  clearTimeout(captureTimer);
  captureTimer = setTimeout(() => capture().catch((error) => updateBadge({ state: "blocked", detail: String(error) })), 1200);
}

new MutationObserver(scheduleCapture).observe(document.documentElement, { childList: true, subtree: true });
setInterval(scheduleCapture, 20_000);
chrome.runtime.sendMessage({ type: "glassbox-status" }, updateBadge);
scheduleCapture();
