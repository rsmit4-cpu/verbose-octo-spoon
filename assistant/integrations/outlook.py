"""Outlook-agenda via Microsoft Graph.

Eenmalig koppelen: `python -m assistant.setup_outlook` (apparaatcode-login, werkt ook op je telefoon).
"""
from __future__ import annotations

from pathlib import Path

import msal
import requests

SCOPES = ["Calendars.ReadWrite"]
GRAPH = "https://graph.microsoft.com/v1.0"


def _app(client_id: str, tenant: str, cache_path: Path):
    cache = msal.SerializableTokenCache()
    if cache_path.exists():
        cache.deserialize(cache_path.read_text())
    app = msal.PublicClientApplication(
        client_id, authority=f"https://login.microsoftonline.com/{tenant}", token_cache=cache
    )
    return app, cache


class OutlookClient:
    def __init__(self, client_id: str, tenant: str, cache_path: Path):
        self.app, self.cache = _app(client_id, tenant, cache_path)
        self.cache_path = cache_path

    def _token(self) -> str:
        accounts = self.app.get_accounts()
        result = self.app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
        if not result or "access_token" not in result:
            raise RuntimeError("Outlook is niet (meer) gekoppeld. Voer `python -m assistant.setup_outlook` uit.")
        if self.cache.has_state_changed:
            self.cache_path.write_text(self.cache.serialize())
        return result["access_token"]

    def _req(self, method: str, path: str, tz: str, **kw) -> dict:
        headers = {"Authorization": f"Bearer {self._token()}", "Prefer": f'outlook.timezone="{tz}"'}
        r = requests.request(method, GRAPH + path, headers=headers, timeout=30, **kw)
        r.raise_for_status()
        return r.json()

    def list_events(self, start_iso: str, end_iso: str, tz: str) -> list[dict]:
        data = self._req(
            "GET", "/me/calendarView", tz,
            params={"startDateTime": start_iso, "endDateTime": end_iso,
                    "$orderby": "start/dateTime", "$top": 50,
                    "$select": "id,subject,start,end,location"},
        )
        return [
            {
                "id": e["id"],
                "titel": e.get("subject"),
                "start": e["start"]["dateTime"],
                "eind": e["end"]["dateTime"],
                "locatie": (e.get("location") or {}).get("displayName"),
            }
            for e in data.get("value", [])
        ]

    def create_event(self, title: str, start_local: str, end_local: str, tz: str,
                     location: str | None, description: str | None) -> dict:
        body = {
            "subject": title,
            "start": {"dateTime": start_local, "timeZone": tz},
            "end": {"dateTime": end_local, "timeZone": tz},
        }
        if location:
            body["location"] = {"displayName": location}
        if description:
            body["body"] = {"contentType": "text", "content": description}
        e = self._req("POST", "/me/events", tz, json=body)
        return {"id": e["id"], "link": e.get("webLink")}
