"""WhatsApp Business Cloud API (Meta): berichten versturen, media downloaden, webhooks controleren."""
from __future__ import annotations

import hashlib
import hmac
import logging
from pathlib import Path

import aiohttp

log = logging.getLogger(__name__)

TEXT_LIMIT = 4000          # WhatsApp staat 4096 tekens toe
BUTTON_BODY_LIMIT = 1000   # interactieve berichten: max 1024 tekens
REENGAGEMENT_ERROR = 131047  # buiten het 24-uursvenster: alleen sjabloonberichten toegestaan


class WhatsAppError(RuntimeError):
    def __init__(self, status: int, data: dict):
        err = data.get("error", {}) if isinstance(data, dict) else {}
        self.code = err.get("code")
        super().__init__(f"WhatsApp API {status}: {err.get('message', data)}")


def valid_signature(app_secret: str, body: bytes, header: str) -> bool:
    """Controleer X-Hub-Signature-256 zodat alleen Meta berichten kan afleveren."""
    expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")


def chunks(text: str, size: int = TEXT_LIMIT):
    for i in range(0, len(text), size):
        yield text[i:i + size]


class WhatsApp:
    def __init__(self, token: str, phone_number_id: str, api_version: str = "v23.0"):
        self.base = f"https://graph.facebook.com/{api_version}"
        self.phone_number_id = phone_number_id
        self.headers = {"Authorization": f"Bearer {token}"}
        self._session: aiohttp.ClientSession | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.headers, timeout=aiohttp.ClientTimeout(total=60))
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _post(self, payload: dict) -> dict:
        body = {"messaging_product": "whatsapp", **payload}
        async with self.session.post(f"{self.base}/{self.phone_number_id}/messages", json=body) as r:
            data = await r.json(content_type=None)
            if r.status >= 400:
                raise WhatsAppError(r.status, data)
            return data

    async def send_text(self, to: int | str, text: str) -> None:
        for part in chunks(text):
            await self._post({"to": str(to), "type": "text", "text": {"body": part, "preview_url": False}})

    async def send_buttons(self, to: int | str, body: str, buttons: list[tuple[str, str]]) -> None:
        """Max 3 knoppen; (id, titel ≤ 20 tekens)."""
        await self._post({
            "to": str(to),
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body[:BUTTON_BODY_LIMIT]},
                "action": {"buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": title[:20]}} for bid, title in buttons
                ]},
            },
        })

    async def send_template(self, to: int | str, name: str, language: str, params: list[str]) -> None:
        await self._post({
            "to": str(to),
            "type": "template",
            "template": {
                "name": name,
                "language": {"code": language},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}],
            },
        })

    async def mark_read(self, message_id: str) -> None:
        try:
            await self._post({"status": "read", "message_id": message_id})
        except Exception:  # niet belangrijk genoeg om op te falen
            log.debug("Markeren als gelezen mislukt", exc_info=True)

    async def download_media(self, media_id: str, dest: Path) -> Path:
        async with self.session.get(f"{self.base}/{media_id}") as r:
            meta = await r.json(content_type=None)
            if r.status >= 400:
                raise WhatsAppError(r.status, meta)
        async with self.session.get(meta["url"]) as r:
            r.raise_for_status()
            dest.write_bytes(await r.read())
        return dest
