from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
ENV_FILE = PROJECT_ROOT / ".env"


def load_environment():
    load_dotenv(ENV_FILE)
