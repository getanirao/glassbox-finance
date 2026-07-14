import os
import sys
import argparse
import asyncio
from dotenv import load_dotenv

load_dotenv()

os.environ["MPLBACKEND"] = "Agg"

from config import DATA_DIR
from engine import EngineRunner, handle_reset, run_news_worker


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Glassbox Finance — Wolves of Wall Street",
        add_help=True,
    )
    parser.add_argument("--sandbox", action="store_true",
                        help="Run in SANDBOX mode")
    parser.add_argument("--comp", action="store_true",
                        help="Run in COMPETITION mode (default)")
    parser.add_argument("--clear", action="store_true",
                        help="Purge state files and reset")
    parser.add_argument("--bot", action="store_true",
                        help="Start Discord bot alongside engine")
    parser.add_argument("--bot-only", action="store_true",
                        help="Start only the Discord bot, no engine")
    parser.add_argument("--engine", action="store_true",
                        help="Start only the recommendation engine")
    parser.add_argument("--news-worker", action="store_true",
                        help="Continuously fetch and score news without Discord or recommendations")
    parser.add_argument("--news-worker-once", action="store_true",
                        help="Run one fetch/score news cycle and exit")
    parser.add_argument("--token", type=str, default=None,
                        help="Discord bot token (overrides BOT_TOKEN env)")
    return parser.parse_args()


def main():
    args = parse_args()
    ensure_data_dir()

    if args.clear:
        handle_reset()
        sys.exit(0)

    if args.sandbox and args.comp:
        print("  Error: --sandbox and --comp are mutually exclusive.")
        sys.exit(1)
    if (args.news_worker or args.news_worker_once) and (args.bot or args.bot_only or args.engine):
        print("  Error: news-worker modes cannot be combined with --bot, --bot-only, or --engine.")
        sys.exit(1)

    if args.news_worker or args.news_worker_once:
        run_news_worker(once=args.news_worker_once, send_roundup=False)
        sys.exit(0)

    from config import RUN_MODE_FILE
    if args.sandbox:
        run_mode = "SANDBOX"
    elif args.comp:
        run_mode = "COMPETITION"
    elif os.path.exists(RUN_MODE_FILE):
        run_mode = open(RUN_MODE_FILE).read().strip()
    else:
        run_mode = os.environ.get("RUN_MODE", "COMPETITION")

    if not args.sandbox and not args.comp and not args.bot and not args.bot_only and not args.engine:
        print("\n  Glassbox Finance — Wolves of Wall Street")
        print("  " + "-" * 50)
        print("  Usage: python main.py [--comp] [--bot | --bot-only | --engine | --news-worker | --news-worker-once] [--clear]")
        print()
        print("  --comp       Competition advisory desk (default)")
        print("  --bot        Start Discord bot + engine")
        print("  --bot-only   Start only the Discord bot")
        print("  --engine     Start only the recommendation engine")
        print("  --news-worker       Continuously fetch and score news only")
        print("  --news-worker-once  Fetch and score news once, then exit")
        print("  --clear      Purge state files")
        print("  " + "-" * 50 + "\n")
        if not args.bot and not args.bot_only:
            pass  # default to COMPETITION below

    engine_thread = None
    engine = None
    bot_task = None

    if not args.bot_only:
        engine = EngineRunner(run_mode=run_mode)
        engine.start()
        print(f"  [Engine] Started in {run_mode} mode (data dir: {DATA_DIR}/)")

    if args.bot or args.bot_only:
        token = args.token or os.environ.get("BOT_TOKEN", "")
        if not token:
            print("  [Bot] No BOT_TOKEN set. Use --token or BOT_TOKEN env.")
            sys.exit(1)

        from bot import GlassboxBot
        bot = GlassboxBot(engine_runner=engine)

        async def run_bot():
            try:
                await bot.start(token)
            except KeyboardInterrupt:
                await bot.close()

        try:
            asyncio.run(run_bot())
        except KeyboardInterrupt:
            pass
    else:
        print(f"  [Engine] Running without bot. Use --bot to add Discord slash commands.")
        try:
            while True:
                import time
                time.sleep(3600)
        except KeyboardInterrupt:
            pass

    if engine:
        engine.stop()
    print(f"\n{'=' * 80}")
    print(f"                             ENGINE SYSTEM TERMINATED")
    print(f"{'=' * 80}")
    print(f"  Core operational data cache and local state files preserved in {DATA_DIR}/.")
    print(f"{'=' * 80}")


if __name__ == "__main__":
    main()
