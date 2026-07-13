import os

DATA_DIR = "data"

STARTING_CAPITAL = 100000
GATE_HOURS = 24
LOOP_INTERVAL_MINUTES = 60
VOLATILITY_THRESHOLD = 0.005
VOLATILITY_WINDOW = 5
GRACE_MINUTES = 30
WARMUP_MINUTES = 10
LONG_WINDOW_HOURS = 504
LONG_SENTIMENT_WEIGHT = 0.3
DECAY_HALF_LIFE_HOURS = 336
FINBERT_TEMPERATURE = 0.5
SENTIMENT_BUY_THRESHOLD = 0.0
MAX_BUYS_PER_CYCLE = 6
MAX_POSITION_WEIGHT = 0.30
SENTIMENT_IMPACT = 0.30
WATCHLIST_SCANNER_LIMIT = 75
MAX_PORTFOLIO_HOLDINGS = 12
NEWS_CYCLE_HOURS = 1
NEWS_RATE_MIN = 1.5
NEWS_RATE_MAX = 3.5

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
COMPETITION_CHART = os.path.join(DATA_DIR, "competition_chart.png")
COMPETITION_MESSAGE_STATE = os.path.join(DATA_DIR, ".competition_message_state")
COMPETITION_PREDICTION_FILE = os.path.join(DATA_DIR, ".competition_prediction.json")
EXECUTION_WINDOW_MINUTES = 1

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
