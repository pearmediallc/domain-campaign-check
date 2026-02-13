import os


def env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    return v if v is not None and v != "" else default


REDTRACK_API_BASE = env("REDTRACK_API_BASE", "https://api.redtrack.io")
REDTRACK_API_KEY = env("REDTRACK_API_KEY")

TIMEZONE = env("TIMEZONE", "Asia/Calcutta")
DAYS_LOOKBACK = int(env("DAYS_LOOKBACK", "30") or 30)

DATABASE_URL = env("DATABASE_URL", "sqlite:///./data.sqlite3")

TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = env("TELEGRAM_CHAT_ID")

TELEGRAM_VERBOSE = (env("TELEGRAM_VERBOSE", "false") or "false").lower() in ("1", "true", "yes")  # reserved / unused now
MAX_TELEGRAM_MESSAGES_PER_RUN = int(env("MAX_TELEGRAM_MESSAGES_PER_RUN", "25") or 25)

RESULTS_PATH = env("RESULTS_PATH", "./data/results.json")
MAX_CACHED_RUNS = int(env("MAX_CACHED_RUNS", "30") or 30)

CHECK_TIMEOUT_SECONDS = int(env("CHECK_TIMEOUT_SECONDS", "15") or 15)
CHECK_RETRIES = int(env("CHECK_RETRIES", "2") or 2)
ALERT_ON_FIRST_FAILURE = (env("ALERT_ON_FIRST_FAILURE", "false") or "false").lower() in ("1", "true", "yes")
