import datetime
import os
import tempfile
import unittest

import engine
import marketwatch_sync


class MarketWatchSyncTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_paths = {
            "ledger": engine.COMPETITION_LEDGER,
            "backup": engine.COMPETITION_LEDGER_BACKUP,
            "sync": marketwatch_sync.MARKETWATCH_SYNC_FILE,
        }
        engine.COMPETITION_LEDGER = os.path.join(self.tempdir.name, "ledger.json")
        engine.COMPETITION_LEDGER_BACKUP = os.path.join(self.tempdir.name, "ledger.backup.json")
        marketwatch_sync.MARKETWATCH_SYNC_FILE = os.path.join(self.tempdir.name, "sync.json")
        self.now = datetime.datetime.now(datetime.timezone.utc)

    def tearDown(self):
        engine.COMPETITION_LEDGER = self.original_paths["ledger"]
        engine.COMPETITION_LEDGER_BACKUP = self.original_paths["backup"]
        marketwatch_sync.MARKETWATCH_SYNC_FILE = self.original_paths["sync"]
        self.tempdir.cleanup()

    def envelope(self, positions, cash, activity=None):
        return {
            "schema_version": 1,
            "game_slug": marketwatch_sync.MARKETWATCH_GAME_SLUG,
            "observed_at": self.now.isoformat(),
            "snapshot": {
                "positions_complete": True,
                "positions": positions,
                "cash_balance": cash,
            },
            "activity": activity or [],
        }

    def test_cash_is_required(self):
        with self.assertRaisesRegex(ValueError, "visible MarketWatch cash"):
            marketwatch_sync.process_snapshot(self.envelope([], None))

    def test_temporary_table_lag_recovers_without_reset(self):
        status, _ = marketwatch_sync.process_snapshot(self.envelope([], 100000.0))
        self.assertEqual(status, 200)
        executed_at = (self.now - datetime.timedelta(minutes=2)).isoformat()
        event = {
            "event_id": "lagged-fill-1",
            "ticker": "GOOGL",
            "action": "buy",
            "shares": 10,
            "price": 100.0,
            "executed_at": executed_at,
        }
        status, blocked = marketwatch_sync.process_snapshot(self.envelope([], 100000.0, [event]))
        self.assertEqual(status, 409)
        self.assertEqual(blocked["status"], "blocked_reconciliation")

        status, recovered = marketwatch_sync.process_snapshot(
            self.envelope([{"ticker": "GOOGL", "shares": 10}], 99000.0, [event])
        )
        self.assertEqual(status, 200)
        self.assertEqual(recovered["status"], "healthy")
        ledger = engine.load_competition_ledger()
        self.assertEqual(ledger["trades"][0]["timestamp"], executed_at)
        self.assertEqual(ledger["holdings"]["GOOGL"]["shares"], 10)

    def test_replayed_fill_is_deduplicated(self):
        marketwatch_sync.process_snapshot(self.envelope([], 100000.0))
        event = {
            "event_id": "fill-1",
            "ticker": "MSFT",
            "action": "buy",
            "shares": 5,
            "price": 200.0,
            "executed_at": self.now.isoformat(),
        }
        payload = self.envelope([{"ticker": "MSFT", "shares": 5}], 99000.0, [event])
        self.assertEqual(marketwatch_sync.process_snapshot(payload)[1]["imported"], 1)
        replay = marketwatch_sync.process_snapshot(payload)[1]
        self.assertEqual(replay["duplicates"], 1)
        self.assertEqual(len(engine.load_competition_ledger()["trades"]), 1)


if __name__ == "__main__":
    unittest.main()
