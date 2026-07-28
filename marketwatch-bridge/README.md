# Glassbox MarketWatch Bridge

This unpacked Chrome extension passively reads the visible Portfolio and activity tables for the Wolves of Wall Street game. It does not click, fill, submit, or otherwise change a MarketWatch order.

## Install

1. Start the local receiver in the repository `README.md`.
2. Open `chrome://extensions`, turn on Developer mode, and choose **Load unpacked**.
3. Select this `marketwatch-bridge` folder.
4. Open the extension details, choose **Extension options**, then enter `http://127.0.0.1:8765` and the bridge token.
5. Visit the signed-in Wolves **Portfolio** view and wait for the in-page badge to report `healthy`.

The service worker keeps unacknowledged snapshots in IndexedDB and retries them. Its one-minute browser alarm requests a fresh full-portfolio capture while the signed-in Wolves Portfolio page remains open, so Glassbox can verify that its context is current even when Chrome throttles page timers. If an unpacked-extension reload disconnected the page script, the alarm reinjects `parser-core.js` and `content.js` on the next minute. A receiver rejection is shown as `blocked`; Glassbox also stops publishing final trade instructions until reconciliation is healthy.

## Data Contract

The extension sends only the configured game slug, observation timestamp, normalized visible cash/positions, and normalized buy/sell activity rows. Portfolio and activity tables are selected independently by visible headers and nearby section context. A snapshot is complete only when both the holdings state and visible `Cash Remaining` value are parseable.

Activity rows require a visible timestamp and receive a deterministic event ID, so retries and restarts cannot duplicate a logged fill. Seconds are preserved when MarketWatch displays them; otherwise identical same-minute fills receive stable occurrence suffixes. The receiver retains imported fills in a durable journal and can recover from a temporary incomplete initial page render without requiring a state reset.

If the page changes, is closed, or the extension cannot identify a complete Portfolio plus cash snapshot, it sends nothing and shows `waiting`. This is intentional: a missed sync is safer than an inferred trade. Keep the signed-in Portfolio page open during a market-open recommendation window; closing it correctly lets the bridge become stale and blocks new final instructions.

After updating files in an unpacked installation, click **Reload** on `chrome://extensions` and refresh the Wolves page. The extension version in this release is `1.0.4`.
