import os

DATA_DIR = "data"

STARTING_CAPITAL = 100000
GATE_HOURS = 4
MOMENTUM_IMPACT = 1.0
STOP_LOSS_PERCENT = 0.10
TRAILING_TRIM_PERCENT = 0.05
PROFIT_TAKE_PERCENT = 0.10
LOOP_INTERVAL_MINUTES = 60
VOLATILITY_THRESHOLD = 0.005
VOLATILITY_WINDOW = 5
GRACE_MINUTES = 30
WARMUP_MINUTES = 10
LONG_WINDOW_HOURS = 504
LONG_SENTIMENT_WEIGHT = 0.3
DECAY_HALF_LIFE_HOURS = 336
FINBERT_TEMPERATURE = 0.5
SENTIMENT_BUY_THRESHOLD = 0.15
SENTIMENT_EXIT_THRESHOLD = 0.0
PERSISTENT_SENTIMENT_THRESHOLD = 0.35
MAX_BUYS_PER_CYCLE = 8
MAX_POSITION_WEIGHT = 0.40
MIN_CASH_RESERVE_PERCENT = 0.10
SENTIMENT_IMPACT = 0.30
DOWNSIDE_SENTIMENT_WEIGHT = 1.0
BUSINESS_RISK_SENTIMENT_FLOOR = -0.65
WATCHLIST_SCANNER_LIMIT = 75
CORE_PORTFOLIO_HOLDINGS = 6
MAX_PORTFOLIO_HOLDINGS = 8
MAX_SECTOR_POSITIONS = 2
MAX_FACTOR_POSITIONS = 2
NEWS_CYCLE_HOURS = 1
NEWS_RATE_MIN = 1.5
NEWS_RATE_MAX = 3.5
NEWS_LOCK_STALE_MINUTES = 90
MAX_HEADLINES_PER_TICKER = 30
MAX_LONG_HEADLINES_PER_TICKER_DAY = 5
MIN_PERSISTENT_COVERAGE_HOURS = 72
PRICE_CACHE_SECONDS = 60
FINBERT_INTRA_OP_THREADS = max(1, int(os.getenv("FINBERT_INTRA_OP_THREADS", "2")))
SENTIMENT_SCORING_VERSION = "modern-finbert-int8-t05-v1"

ENABLE_ARTICLE_SUMMARIZATION = os.getenv("ENABLE_ARTICLE_SUMMARIZATION", "false").lower() in {"1", "true", "yes"}
SUMMARIZE_PROVIDER = os.getenv("SUMMARIZE_PROVIDER", "openai").lower()
SUMMARIZE_MAX_CHARS = 4000

GATE_FILE = os.path.join(DATA_DIR, ".last_run")
NEWS_CACHE_FILE = os.path.join(DATA_DIR, ".news_cache.json")
MESSAGE_STATE_FILE = os.path.join(DATA_DIR, ".message_state")
NEWS_MESSAGE_STATE_FILE = os.path.join(DATA_DIR, ".news_message_state")
OBSERVATION_FILE = os.path.join(DATA_DIR, ".observation_state")
NEWS_CYCLE_FILE = os.path.join(DATA_DIR, ".last_news_run")
NEWS_LOCK_FILE = os.path.join(DATA_DIR, ".news_lock")
NEWS_CACHE_BACKUP = os.path.join(DATA_DIR, ".news_cache.backup.json")
RUN_MODE_FILE = os.path.join(DATA_DIR, ".run_mode")
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

INSTITUTIONAL_BANKS = {"JPM", "GS", "BAC", "MS", "C"}

COMPETITION_LEDGER = os.path.join(DATA_DIR, "competition_ledger.json")
COMPETITION_LEDGER_BACKUP = os.path.join(DATA_DIR, "competition_ledger.backup.json")
COMPETITION_MESSAGE_STATE = os.path.join(DATA_DIR, ".competition_message_state")
COMPETITION_PREDICTION_FILE = os.path.join(DATA_DIR, ".competition_prediction.json")
COMPETITION_EXECUTION_PLAN_FILE = os.path.join(DATA_DIR, ".competition_execution_plan.json")
FUNDAMENTALS_CACHE_FILE = os.path.join(DATA_DIR, ".fundamentals_cache.json")
FUNDAMENTALS_CACHE_TTL_HOURS = 24
EXECUTION_WINDOW_MINUTES = 15
ENGINE_HEALTH_FILE = os.path.join(DATA_DIR, ".engine_health.json")
ENGINE_HEALTH_MAX_STALENESS_SECONDS = 900

# Opt-in bridge; execution recommendations fail closed until a verified snapshot arrives.
MARKETWATCH_SYNC_ENABLED = os.getenv("MARKETWATCH_SYNC_ENABLED", "false").lower() in {"1", "true", "yes"}
MARKETWATCH_SYNC_HOST = os.getenv("MARKETWATCH_SYNC_HOST", "0.0.0.0")
MARKETWATCH_SYNC_PORT = int(os.getenv("MARKETWATCH_SYNC_PORT", "8765"))
MARKETWATCH_SYNC_TOKEN = os.getenv("MARKETWATCH_SYNC_TOKEN", "")
MARKETWATCH_SYNC_FILE = os.path.join(DATA_DIR, "marketwatch_sync_state.json")
MARKETWATCH_GAME_SLUG = os.getenv("MARKETWATCH_GAME_SLUG", "wolves-of-wall-street---july-2026")
MARKETWATCH_SYNC_MAX_STALENESS_SECONDS = int(os.getenv("MARKETWATCH_SYNC_MAX_STALENESS_SECONDS", "300"))

NYSE_FULL_DAY_CLOSURES_2026 = {
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-04-03",
    "2026-05-25",
    "2026-06-19",
    "2026-07-03",
    "2026-09-07",
    "2026-11-26",
    "2026-12-25",
}

NYSE_EARLY_CLOSES_2026 = {
    "2026-11-27": "13:00",
    "2026-12-24": "13:00",
}

TICKERS = [
    "AAPL", "MSFT", "GOOGL", "META", "NVDA", "INTC", "AMD", "CSCO",
    "CRM", "ORCL", "IBM", "ADBE", "NFLX", "NOW",
    "JNJ", "PFE", "UNH", "ABBV", "MRK", "ABT", "TMO", "LLY",
    "BMY", "MDT", "DHR", "AMGN",
    "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "HAL", "MPC", "PSX", "VLO",
    "AMZN", "TSLA", "HD", "MCD", "NKE", "DIS", "SBUX", "LOW",
    "BKNG", "TGT", "TJX", "ROST",
    "CAT", "GE", "BA", "HON", "RTX", "UPS", "UNP", "LMT",
    "GD", "CARR", "EMR", "ETN",
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "PEG", "ED", "WEC",
    "JPM", "GS", "BAC", "MS", "C",
]

TICKER_SECTORS = {
    **dict.fromkeys({"AAPL", "MSFT", "GOOGL", "META", "NVDA", "INTC", "AMD", "CSCO", "CRM", "ORCL", "IBM", "ADBE", "NOW"}, "Technology"),
    **dict.fromkeys({"NFLX", "DIS"}, "Communication"),
    **dict.fromkeys({"JNJ", "PFE", "UNH", "ABBV", "MRK", "ABT", "TMO", "LLY", "BMY", "MDT", "DHR", "AMGN"}, "Healthcare"),
    **dict.fromkeys({"XOM", "CVX", "COP", "SLB", "EOG", "OXY", "HAL", "MPC", "PSX", "VLO"}, "Energy"),
    **dict.fromkeys({"AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "BKNG", "TGT", "TJX", "ROST"}, "Consumer"),
    **dict.fromkeys({"CAT", "GE", "BA", "HON", "RTX", "UPS", "UNP", "LMT", "GD", "CARR", "EMR", "ETN"}, "Industrials"),
    **dict.fromkeys({"NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "PEG", "ED", "WEC"}, "Utilities"),
    **dict.fromkeys({"JPM", "GS", "BAC", "MS", "C"}, "Financials"),
}

FACTOR_BUCKETS = {
    "growth_ai": frozenset({"META", "GOOGL", "MSFT", "NVDA", "NFLX"}),
}

TICKER_NAMES = {
    "AAPL": "apple", "MSFT": "microsoft", "GOOGL": "alphabet", "META": "meta",
    "NVDA": "nvidia", "INTC": "intel", "AMD": "amd", "CSCO": "cisco",
    "CRM": "salesforce", "ORCL": "oracle", "IBM": "ibm", "ADBE": "adobe",
    "NFLX": "netflix", "NOW": "servicenow",
    "JNJ": "johnson", "PFE": "pfizer", "UNH": "unitedhealth", "ABBV": "abbvie",
    "MRK": "merck", "ABT": "abbott", "TMO": "thermo fisher", "LLY": "eli lilly",
    "BMY": "bristol myers", "MDT": "medtronic", "DHR": "danaher", "AMGN": "amgen",
    "XOM": "exxon", "CVX": "chevron", "COP": "conocophillips", "SLB": "schlumberger",
    "EOG": "eog resources", "OXY": "occidental", "HAL": "halliburton",
    "MPC": "marathon petroleum", "PSX": "phillips 66", "VLO": "valero",
    "AMZN": "amazon", "TSLA": "tesla", "HD": "home depot", "MCD": "mcdonald",
    "NKE": "nike", "DIS": "disney", "SBUX": "starbucks", "LOW": "lowe",
    "BKNG": "booking", "TGT": "target", "TJX": "tjx", "ROST": "ross",
    "CAT": "caterpillar", "GE": "general electric", "BA": "boeing",
    "HON": "honeywell", "RTX": "raytheon", "UPS": "ups", "UNP": "union pacific",
    "LMT": "lockheed martin", "GD": "general dynamics", "CARR": "carrier",
    "EMR": "emerson", "ETN": "eaton",
    "NEE": "next era", "DUK": "duke energy", "SO": "southern company",
    "D": "dominion energy", "AEP": "american electric", "EXC": "exelon",
    "SRE": "sempra", "PEG": "public service", "ED": "consolidated edison",
    "WEC": "wec energy",
    "JPM": "jpmorgan", "GS": "goldman sachs", "BAC": "bank of america",
    "MS": "morgan stanley", "C": "citigroup",
}


DISCORD_ADMIN_ROLE = "Admin"
DISCORD_TRADER_ROLE = "Trader"
BOT_COMMAND_PREFIX = "/"

from lexicon import POSITIVE_LEXICON, NEGATIVE_LEXICON, CRITICAL_NEGATIVE_LEXICON
