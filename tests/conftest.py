"""Load .env so DAFNY_PATH is visible to the integration test."""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
