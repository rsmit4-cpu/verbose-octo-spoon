"""Configuratie uit omgevingsvariabelen (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()


def _numbers(raw: str) -> tuple[int, ...]:
    """'+31 6 12345678, 3161111' -> (31612345678, 3161111). Het eerste nummer is de eigenaar."""
    out = []
    for part in raw.split(","):
        digits = "".join(c for c in part if c.isdigit())
        if digits:
            out.append(int(digits))
    return tuple(out)


@dataclass(frozen=True)
class Config:
    # WhatsApp Business Cloud API (Meta)
    wa_token: str = os.getenv("WHATSAPP_TOKEN", "")
    wa_phone_number_id: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    wa_app_secret: str = os.getenv("WHATSAPP_APP_SECRET", "")
    wa_verify_token: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    wa_api_version: str = os.getenv("WHATSAPP_API_VERSION", "v23.0")
    wa_reminder_template: str = os.getenv("WHATSAPP_REMINDER_TEMPLATE", "")
    wa_template_language: str = os.getenv("WHATSAPP_TEMPLATE_LANGUAGE", "nl")
    allowed_numbers: tuple[int, ...] = field(default_factory=lambda: _numbers(os.getenv("ALLOWED_NUMBERS", "")))
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
