import datetime
import os
import tempfile
import unittest
from unittest import mock

import engine


class EngineSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.original_paths = {
            "ledger": engine.COMPETITION_LEDGER,
            "backup": engine.COMPETITION_LEDGER_BACKUP,
            "plan": engine.COMPETITION_EXECUTION_PLAN_FILE,
            "news_cache": engine.NEWS_CACHE_FILE,
            "news_backup": engine.NEWS_CACHE_BACKUP,
        }
        engine.COMPETITION_LEDGER = os.path.join(self.tempdir.name, "ledger.json")
        engine.COMPETITION_LEDGER_BACKUP = os.path.join(self.tempdir.name, "ledger.backup.json")
        engine.COMPETITION_EXECUTION_PLAN_FILE = os.path.join(self.tempdir.name, "plan.json")
        engine.NEWS_CACHE_FILE = os.path.join(self.tempdir.name, "news.json")
        engine.NEWS_CACHE_BACKUP = os.path.join(self.tempdir.name, "news.backup.json")

    def tearDown(self):
        engine.COMPETITION_LEDGER = self.original_paths["ledger"]
        engine.COMPETITION_LEDGER_BACKUP = self.original_paths["backup"]
        engine.COMPETITION_EXECUTION_PLAN_FILE = self.original_paths["plan"]
        engine.NEWS_CACHE_FILE = self.original_paths["news_cache"]
        engine.NEWS_CACHE_BACKUP = self.original_paths["news_backup"]
        self.tempdir.cleanup()

    def test_trade_journal_survives_observation_trim(self):
        with mock.patch.object(engine, "_holdings_value", return_value=0.0):
            engine.record_trade(
                "GOOGL", "buy", 1, 100.0,
                source="marketwatch", event_id="journal-1",
            )
            ledger = engine.load_competition_ledger()
            ledger["history"] = [
                {"timestamp": str(index), "portfolio_value": 100000.0}
                for index in range(500)
            ]
            engine.save_competition_ledger(ledger)
            engine._visualization_update_unlocked(record_history=True)
        ledger = engine.load_competition_ledger()
        self.assertEqual(len(ledger["history"]), 500)
        self.assertEqual([trade["event_id"] for trade in ledger["trades"]], ["journal-1"])

    def test_execution_plan_persists_and_decrements_with_fills(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        engine.save_execution_plan([
            {
                "ticker": "GOOGL",
                "action": "BUY",
                "target_shares": 10,
                "price": 100.0,
                "weight": 0.2,
                "reason": "core_conviction",
            }
        ], issued_at=now)
        self.assertEqual(engine.load_active_execution_plan()["recs"][0]["target_shares"], 10)
        with mock.patch.object(engine, "_holdings_value", return_value=0.0):
            engine.record_trade(
                "GOOGL", "buy", 4, 100.0, trade_time=now.isoformat(),
                source="marketwatch", event_id="partial-1",
            )
        self.assertEqual(engine.load_active_execution_plan()["recs"][0]["target_shares"], 6)
        with mock.patch.object(engine, "_holdings_value", return_value=0.0):
            engine.record_trade(
                "GOOGL", "buy", 6, 100.0, trade_time=now.isoformat(),
                source="marketwatch", event_id="partial-2",
            )
        self.assertIsNone(engine.load_active_execution_plan())

    def test_allocation_preserves_cash_reserve(self):
        candidates = [
            {"ticker": ticker, "adjusted_score": score}
            for ticker, score in (("A", 130), ("B", 125), ("C", 124), ("D", 112))
        ]
        weights = engine.capped_score_weights(candidates)
        self.assertAlmostEqual(sum(weights.values()), 0.9)
        self.assertTrue(all(weight <= engine.MAX_POSITION_WEIGHT for weight in weights.values()))

    def test_prune_retains_sampled_long_history(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        old = now - datetime.timedelta(days=10)
        headlines = []
        for index in range(40):
            headlines.append({
                "ticker": "GOOGL",
                "text": f"current headline {index}",
                "timestamp": (now - datetime.timedelta(minutes=index)).isoformat(),
                "net_score": 0.2,
                "pos_count": 0.6,
                "neg_count": 0.1,
            })
            headlines.append({
                "ticker": "GOOGL",
                "text": f"historical headline {index}",
                "timestamp": (old - datetime.timedelta(minutes=index)).isoformat(),
                "net_score": -0.2,
                "pos_count": 0.1,
                "neg_count": 0.6,
            })
        cache = {"headlines": headlines}
        engine.prune_news_cache(cache)
        self.assertEqual(len(cache["headlines"]), 35)
        self.assertGreater(engine.sentiment_coverage_hours(cache["headlines"], "GOOGL"), 200)

    def test_reserve_slot_requires_long_signal_coverage(self):
        tickers = ["GOOGL", "JNJ", "PSX", "AMZN", "ETN", "NEE", "JPM"]
        predicted = [
            {
                "ticker": ticker,
                "passed": True,
                "sentiment": 0.6,
                "long_sentiment": 0.6,
                "long_coverage_hours": 0.0,
                "adjusted_score": 120 - index,
                "health_score": 100.0,
            }
            for index, ticker in enumerate(tickers)
        ]
        ledger = {"cash_balance": 100000.0, "holdings": {}, "history": [], "trades": []}
        with mock.patch.object(engine, "_get_price", return_value=100.0):
            _, display = engine.compute_recommendations(predicted, ledger, predicted)
        jpm = next(row for row in display if row["ticker"] == "JPM")
        self.assertEqual(jpm["display_reason"], "long_signal_warmup")

    def test_scorer_version_migration_is_persisted_immediately(self):
        cache = {"headlines": [], "scoring_version": None}

        def migrate(target):
            target["scoring_version"] = "test-model:onnx"
            return 0

        with mock.patch.object(engine, "repair_news_cache", side_effect=migrate):
            engine.repair_and_persist_news_cache(cache)

        persisted = engine._read_json(engine.NEWS_CACHE_FILE)
        self.assertEqual(persisted["scoring_version"], "test-model:onnx")


if __name__ == "__main__":
    unittest.main()
