"""Google Agenda + Gmail via de officiële Google API-client.

Eenmalig koppelen: `python -m assistant.setup_google` (opent een browser voor toestemming).
"""
from __future__ import annotations

import base64
from email.message import EmailMessage
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
]


class GoogleClient:
    def __init__(self, token_path: Path):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
            token_path.write_text(creds.to_json())
        self.calendar = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self.gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)

    # ---------- agenda ----------
    def list_events(self, start_iso: str, end_iso: str, max_results: int = 25) -> list[dict]:
        res = self.calendar.events().list(
            calendarId="primary", timeMin=start_iso, timeMax=end_iso,
            singleEvents=True, orderBy="startTime", maxResults=max_results,
        ).execute()
        return [
            {
                "id": e["id"],
                "titel": e.get("summary", "(geen titel)"),
                "start": e["start"].get("dateTime", e["start"].get("date")),
                "eind": e["end"].get("dateTime", e["end"].get("date")),
                "locatie": e.get("location"),
            }
            for e in res.get("items", [])
        ]

    def create_event(self, title: str, start_iso: str, end_iso: str, tz: str,
                     location: str | None, description: str | None) -> dict:
        body = {
            "summary": title,
            "start": {"dateTime": start_iso, "timeZone": tz},
            "end": {"dateTime": end_iso, "timeZone": tz},
        }
        if location:
            body["location"] = location
        if description:
            body["description"] = description
        e = self.calendar.events().insert(calendarId="primary", body=body).execute()
        return {"id": e["id"], "link": e.get("htmlLink")}

    # ---------- Gmail ----------
    def search_mail(self, query: str, max_results: int = 10) -> list[dict]:
        res = self.gmail.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
        out = []
        for m in res.get("messages", []):
            msg = self.gmail.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
            out.append({
                "id": m["id"],
                "van": headers.get("From"),
                "onderwerp": headers.get("Subject"),
                "datum": headers.get("Date"),
                "fragment": msg.get("snippet"),
            })
        return out

    def read_mail(self, message_id: str) -> dict:
        msg = self.gmail.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
        return {
            "van": headers.get("From"),
            "aan": headers.get("To"),
            "onderwerp": headers.get("Subject"),
            "datum": headers.get("Date"),
            "tekst": _plain_text(msg["payload"])[:20000],
        }

    def _raw(self, to: str, subject: str, body: str) -> str:
        em = EmailMessage()
        em["To"], em["Subject"] = to, subject
        em.set_content(body)
        return base64.urlsafe_b64encode(em.as_bytes()).decode()

    def create_draft(self, to: str, subject: str, body: str) -> str:
        d = self.gmail.users().drafts().create(
            userId="me", body={"message": {"raw": self._raw(to, subject, body)}}
        ).execute()
        return d["id"]

    def send(self, to: str, subject: str, body: str) -> str:
        m = self.gmail.users().messages().send(
            userId="me", body={"raw": self._raw(to, subject, body)}
        ).execute()
        return m["id"]


def _plain_text(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode(errors="replace")
    for part in payload.get("parts", []) or []:
        text = _plain_text(part)
        if text:
            return text
    return ""
