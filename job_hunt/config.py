import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
# Persistent data (e.g. Instagram media -> application link). Kept outside
# OUTPUT_DIR because output/ is wiped on every start.
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
ENV_FILE = PROJECT_ROOT / ".env"


def load_environment():
    load_dotenv(ENV_FILE)


def env_flag(name, default=False):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def comment_to_dm_enabled():
    return env_flag("COMMENT_TO_DM_ENABLED", True)


def comment_keyword():
    """Word shown on the card/caption ("Comment LINK"). None when disabled."""
    if not comment_to_dm_enabled():
        return None
    return (os.getenv("COMMENT_KEYWORD") or "LINK").strip().upper() or "LINK"
