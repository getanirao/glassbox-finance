const test = require("node:test");
const assert = require("node:assert/strict");

const parser = require("../marketwatch-bridge/parser-core.js");

test("parses the visible Cash Remaining label", () => {
  assert.equal(parser.parseCashBalance("Cash Remaining ? $100,000.00 Buying Power $100,000.00"), 100000);
});

test("chooses holdings instead of an activity table", () => {
  const activity = {
    visible: true,
    context: "Recent Activity",
    headers: ["symbol", "action", "shares", "price", "date"],
    rows: [["MSFT", "Buy", "5", "$200.00", "Jul 28, 2026 9:40 AM"]]
  };
  const holdings = {
    visible: true,
    context: "Your Portfolio Holdings",
    headers: ["symbol", "shares", "current price"],
    rows: [["MSFT", "5", "$200.00"]]
  };
  assert.deepEqual(parser.parsePortfolio([activity, holdings], "Your Portfolio"), {
    positions_complete: true,
    positions: [{ ticker: "MSFT", shares: 5 }]
  });
});

test("parses activity timestamps and distinguishes identical fills", () => {
  const table = {
    visible: true,
    context: "Transaction Activity",
    headers: ["symbol", "transaction type", "quantity", "fill price", "date", "time"],
    rows: [
      ["GOOGL", "Bought", "10", "$326.56", "Jul 28, 2026", "9:40:15 AM"],
      ["GOOGL", "Bought", "10", "$326.56", "Jul 28, 2026", "9:40:15 AM"]
    ]
  };
  const rows = parser.parseActivity([table]);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].executed_at, "2026-07-28T13:40:15.000Z");
  assert.notEqual(rows[0].stable, rows[1].stable);
  assert.deepEqual(parser.parseActivity([table]), rows);
});

test("recognizes a complete empty portfolio", () => {
  assert.deepEqual(parser.parsePortfolio([], "Your Portfolio You currently have no holdings"), {
    positions_complete: true,
    positions: []
  });
});
