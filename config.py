"""Settings, read from a `.env` file next to this script (copy `.env.example`) or from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PROMPT_PATH = ROOT / "prompts" / "instagram_prompt.md"
POSTS_PATH = DATA_DIR / "posts.csv"
REQUEST_LOG = DATA_DIR / "requests.jsonl"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def _flag(name: str, default: str) -> bool:
    # An empty value (e.g. a missing GitHub secret) uses the default, so a forgotten
    # DRY_RUN never switches to live posting by accident.
    return (os.getenv(name) or default).strip().lower() in {"1", "true", "yes", "on"}


class ConfigError(RuntimeError):
    """A setup problem, such as a missing key. Nothing is posted and nothing is lost."""


@dataclass(frozen=True)
class Settings:
    dry_run: bool = _flag("DRY_RUN", "true")          # true = nothing is sent to Instagram
    timezone: str = os.getenv("TIMEZONE") or "Asia/Kolkata"
    brand_name: str = os.getenv("BRAND_NAME") or "discreetUS"
    waitlist_url: str = os.getenv("WAITLIST_URL", "")

    # Writing: Google Gemini API free tier (aistudio.google.com/apikey, no card needed)
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"   # falls back to older ones (writer.py)

    # reel = animated video (media_reels.py), card = still image (media_cards.py)
    post_format: str = (os.getenv("DAILY_FORMAT") or "reel").strip().lower()
    # Public folder URL Instagram downloads media from. The GitHub workflow sets it for you.
    media_base_url: str = os.getenv("MEDIA_BASE_URL", "")

    # Instagram Business or Creator account. A system-user token from "API setup with Unified login"
    # (doesn't expire) and the account's ID. No Facebook Page needed.
    ig_access_token: str = os.getenv("IG_ACCESS_TOKEN", "")
    ig_user_id: str = os.getenv("IG_USER_ID", "")
    graph_api_version: str = os.getenv("GRAPH_API_VERSION", "")   # empty = your app's default version


SETTINGS = Settings()
DATA_DIR.mkdir(exist_ok=True)
