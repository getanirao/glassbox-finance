(function attachParser(root, factory) {
  const parser = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = parser;
  root.GlassboxMarketWatchParser = parser;
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
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

  function parseCashBalance(pageText) {
    const text = clean(pageText);
    const match = text.match(/cash(?:\s+(?:balance|remaining))?\s*\??\s*[:$]?\s*\$?([\d,]+(?:\.\d{2})?)/i);
    return match ? numberFrom(match[1]) : null;
  }

  function tableScore(table, kind) {
    const context = clean(table.context).toLowerCase();
    let score = table.visible === false ? -1000 : 1;
    if (kind === "portfolio") {
      if (context.includes("portfolio") || context.includes("holdings")) score += 20;
      if (context.includes("activity") || context.includes("transaction")) score -= 50;
    } else {
      if (context.includes("activity") || context.includes("transaction")) score += 20;
      if (context.includes("portfolio") || context.includes("holdings")) score -= 10;
    }
    return score;
  }

  function parsePortfolio(tables, pageText) {
    const candidates = [];
    for (const table of tables) {
      if (table.visible === false) continue;
      const tickerIndex = headerIndex(table.headers, ["ticker", "symbol"]);
      const sharesIndex = headerIndex(table.headers, ["shares", "quantity", "qty"]);
      if (tickerIndex < 0 || sharesIndex < 0) continue;
      const actionIndex = headerIndex(table.headers, ["action", "transaction type", "trade type", "order type"]);
      const timestampIndex = headerIndex(table.headers, ["executed", "date", "time"]);
      if (actionIndex >= 0 && timestampIndex >= 0) continue;
      const positions = [];
      for (const row of table.rows) {
        const ticker = clean(row[tickerIndex]).toUpperCase();
        const shares = integerFrom(row[sharesIndex]);
        if (/^[A-Z.]{1,8}$/.test(ticker) && shares) positions.push({ ticker, shares });
      }
      candidates.push({ score: tableScore(table, "portfolio"), positions });
    }
    candidates.sort((a, b) => b.score - a.score);
    if (candidates.length) return { positions_complete: true, positions: candidates[0].positions };
    const normalizedPage = clean(pageText).toLowerCase();
    if (normalizedPage.includes("your portfolio") && normalizedPage.includes("you currently have no holdings")) {
      return { positions_complete: true, positions: [] };
    }
    return { positions_complete: false, positions: [] };
  }

  function partsInZone(date) {
    const values = {};
    for (const part of new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23"
    }).formatToParts(date)) {
      if (part.type !== "literal") values[part.type] = Number(part.value);
    }
    return values;
  }

  function easternTimestamp(value) {
    const text = clean(value);
    const match = text.match(/(?:([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{4})|(\d{1,2})\/(\d{1,2})\/(\d{4})).*?(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)/i);
    if (!match) return null;
    const months = { jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6, jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12 };
    const month = match[1] ? months[match[1].slice(0, 3).toLowerCase()] : Number(match[4]);
    const day = Number(match[2] || match[5]);
    const year = Number(match[3] || match[6]);
    let hour = Number(match[7]);
    const minute = Number(match[8]);
    const second = Number(match[9] || 0);
    if (match[10].toUpperCase() === "PM" && hour !== 12) hour += 12;
    if (match[10].toUpperCase() === "AM" && hour === 12) hour = 0;
    if (!month || !day || !year) return null;
    const target = Date.UTC(year, month - 1, day, hour, minute, second);
    let guess = target;
    for (let i = 0; i < 3; i += 1) {
      const current = partsInZone(new Date(guess));
      const displayed = Date.UTC(current.year, current.month - 1, current.day, current.hour, current.minute, current.second);
      guess += target - displayed;
    }
    return new Date(guess).toISOString();
  }

  function parseActivity(tables) {
    const candidates = [];
    for (const table of tables) {
      if (table.visible === false) continue;
      const tickerIndex = headerIndex(table.headers, ["ticker", "symbol"]);
      let actionIndex = headerIndex(table.headers, ["action", "transaction type", "trade type", "order type"]);
      if (actionIndex < 0) actionIndex = table.headers.findIndex((header) => header === "order");
      const sharesIndex = headerIndex(table.headers, ["shares", "quantity", "qty"]);
      const priceIndex = headerIndex(table.headers, ["price", "fill"]);
      const timestampIndices = table.headers
        .map((header, index) => (/executed|date|time/.test(header) ? index : -1))
        .filter((index) => index >= 0);
      const referenceIndex = headerIndex(table.headers, ["order id", "transaction id", "reference", "confirmation"]);
      if ([tickerIndex, actionIndex, sharesIndex, priceIndex].some((index) => index < 0) || !timestampIndices.length) continue;
      candidates.push({
        score: tableScore(table, "activity"),
        table,
        tickerIndex,
        actionIndex,
        sharesIndex,
        priceIndex,
        timestampIndices,
        referenceIndex
      });
    }
    candidates.sort((a, b) => b.score - a.score);
    if (!candidates.length) return [];
    const selected = candidates[0];
    const occurrences = new Map();
    const activity = [];
    for (const row of selected.table.rows) {
      const ticker = clean(row[selected.tickerIndex]).toUpperCase();
      const actionMatch = clean(row[selected.actionIndex]).match(/\b(buy|bought|sell|sold)\b/i);
      const shares = integerFrom(row[selected.sharesIndex]);
      const price = numberFrom(row[selected.priceIndex]);
      const timeText = selected.timestampIndices.map((index) => row[index]).join(" ");
      const executedAt = easternTimestamp(timeText);
      if (!/^[A-Z.]{1,8}$/.test(ticker) || !actionMatch || !shares || !price || !executedAt) continue;
      const action = /buy|bought/i.test(actionMatch[1]) ? "buy" : "sell";
      const reference = selected.referenceIndex >= 0 ? clean(row[selected.referenceIndex]) : "";
      const base = JSON.stringify({ ticker, action, shares, price, executedAt, reference });
      const occurrence = occurrences.get(base) || 0;
      occurrences.set(base, occurrence + 1);
      activity.push({ ticker, action, shares, price, executed_at: executedAt, stable: `${base}|${occurrence}` });
    }
    return activity;
  }

  return {
    clean,
    numberFrom,
    integerFrom,
    parseCashBalance,
    parsePortfolio,
    easternTimestamp,
    parseActivity
  };
}));
