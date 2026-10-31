"""Configuratie uit omgevingsvariabelen (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _ids(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


@dataclass(frozen=True)
class Config:
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    allowed_user_ids: set[int] = field(default_factory=lambda: _ids(os.getenv("ALLOWED_USER_IDS", "")))
    timezone: ZoneInfo = ZoneInfo(os.getenv("TIMEZONE", "Europe/Amsterdam"))
    model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
    effort: str = os.getenv("CLAUDE_EFFORT", "medium")
    data_dir: Path = Path(os.getenv("DATA_DIR", "./data"))
    ms_client_id: str = os.getenv("MS_CLIENT_ID", "")
    ms_tenant: str = os.getenv("MS_TENANT", "consumers")
    api_token: str = os.getenv("API_TOKEN", "")
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "8080"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "assistant.db"

    @property
    def google_credentials(self) -> Path:
        return self.data_dir / "google_credentials.json"

    @property
    def google_token(self) -> Path:
        return self.data_dir / "google_token.json"

    @property
    def ms_token_cache(self) -> Path:
        return self.data_dir / "ms_token_cache.json"


def load() -> Config:
    cfg = Config()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    return cfg
