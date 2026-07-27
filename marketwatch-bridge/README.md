# Glassbox MarketWatch Bridge

This unpacked Chrome extension passively reads the visible Portfolio and activity tables for the Wolves of Wall Street game. It does not click, fill, submit, or otherwise change a MarketWatch order.

## Install

1. Start the local receiver in the repository `README.md`.
2. Open `chrome://extensions`, turn on Developer mode, and choose **Load unpacked**.
3. Select this `marketwatch-bridge` folder.
4. Open the extension details, choose **Extension options**, then enter `http://127.0.0.1:8765` and the bridge token.
5. Visit the signed-in Wolves **Portfolio** view and wait for the in-page badge to report `healthy`.

The service worker keeps unacknowledged snapshots in IndexedDB and retries them. A receiver rejection is shown as `blocked`; Glassbox also stops publishing final trade instructions until the reconciliation is healthy.

## Data Contract

The extension sends only the configured game slug, observation timestamp, normalized visible cash/positions, and normalized buy/sell activity rows. Activity rows require a visible timestamp and receive a deterministic event ID, so retries and restarts cannot duplicate a logged fill.

If the page changes and the extension cannot identify a complete portfolio table, it sends nothing and shows `waiting`. This is intentional: a missed sync is safer than an inferred trade.
