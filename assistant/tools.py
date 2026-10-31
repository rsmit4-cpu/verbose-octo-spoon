"""Gereedschap (tools) dat Claude kan gebruiken, plus de uitvoering ervan."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

from .db import Store

# Callback waarmee de bot de gebruiker om bevestiging vraagt (bijv. vóór het versturen van een mail).
ConfirmFn = Callable[[int, str, dict], Awaitable[None]]


def _tool(name: str, description: str, props: dict, required: list[str] | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": required if required is not None else list(props),
            "additionalProperties": False,
        },
    }


S = {"type": "string"}
S_OPT = {"type": ["string", "null"]}
I = {"type": "integer"}
LOCAL_DT = {"type": "string", "description": "Lokale datum/tijd, formaat YYYY-MM-DDTHH:MM"}

CORE_TOOLS = [
    _tool("add_task", "Voeg een taak/to-do toe.", {
        "title": S,
        "due": {**S_OPT, "description": "Deadline YYYY-MM-DD of YYYY-MM-DDTHH:MM, of null"},
        "notes": S_OPT,
    }),
    _tool("list_tasks", "Toon taken.", {"include_done": {"type": "boolean"}}),
    _tool("complete_task", "Markeer een taak als afgerond.", {"task_id": I}),
    _tool("delete_task", "Verwijder een taak.", {"task_id": I}),
    _tool(
        "create_reminder",
        "Plan een herinnering die als pushbericht op de telefoon van de gebruiker verschijnt.",
        {
            "text": S,
            "when": LOCAL_DT,
            "repeat": {"type": "string", "enum": ["none", "daily", "weekly"]},
        },
    ),
    _tool("list_reminders", "Toon geplande herinneringen.", {}),
    _tool("cancel_reminder", "Annuleer een herinnering.", {"reminder_id": I}),
    _tool(
        "remember",
        "Sla een blijvend feit over de gebruiker op (voorkeuren, namen, favoriete club, enz.).",
        {"fact": S},
    ),
    _tool("recall_memories", "Haal alle opgeslagen feiten over de gebruiker op.", {}),
    _tool("forget_memory", "Verwijder een opgeslagen feit.", {"memory_id": I}),
]

GOOGLE_TOOLS = [
    _tool("google_calendar_list", "Afspraken in Google Agenda tussen twee momenten.", {"start": LOCAL_DT, "end": LOCAL_DT}),
    _tool("google_calendar_create", "Maak een afspraak in Google Agenda.", {
        "title": S, "start": LOCAL_DT, "end": LOCAL_DT, "location": S_OPT, "description": S_OPT,
    }),
    _tool("gmail_search", "Zoek in Gmail met Gmail-zoeksyntax (bijv. 'is:unread newer_than:2d').", {"query": S}),
    _tool("gmail_read", "Lees één e-mail volledig.", {"message_id": S}),
    _tool("gmail_draft", "Maak een concept-e-mail in Gmail (wordt niet verstuurd).", {"to": S, "subject": S, "body": S}),
    _tool(
        "gmail_send",
        "Stel een e-mail op om te versturen. De gebruiker krijgt eerst een bevestigknop; pas na een tik wordt hij verstuurd.",
        {"to": S, "subject": S, "body": S},
    ),
]

OUTLOOK_TOOLS = [
    _tool("outlook_calendar_list", "Afspraken in de Outlook-agenda tussen twee momenten.", {"start": LOCAL_DT, "end": LOCAL_DT}),
    _tool("outlook_calendar_create", "Maak een afspraak in de Outlook-agenda.", {
        "title": S, "start": LOCAL_DT, "end": LOCAL_DT, "location": S_OPT, "description": S_OPT,
    }),
]

WEB_SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}


def parse_local(value: str, tz: ZoneInfo) -> datetime:
    """Lokale tijd ('2026-11-02T20:00') -> tijdzonebewust datetime. Expliciete offsets worden gerespecteerd."""
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


@dataclass
class Toolbox:
    store: Store
    tz: ZoneInfo
    google: Any = None
    outlook: Any = None
    confirm: ConfirmFn | None = None

    def definitions(self) -> list[dict]:
        tools = [*CORE_TOOLS]
        if self.google:
            tools += GOOGLE_TOOLS
        if self.outlook:
            tools += OUTLOOK_TOOLS
        return [*tools, WEB_SEARCH]

    def _fmt_utc(self, iso: str) -> str:
        return datetime.fromisoformat(iso).astimezone(self.tz).strftime("%a %d-%m-%Y %H:%M")

    async def run(self, name: str, args: dict, chat_id: int) -> str:
        handler = getattr(self, f"_t_{name}", None)
        if handler is None:
            raise ValueError(f"Onbekende tool: {name}")
        result = await handler(chat_id=chat_id, **args)
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)

    # ---------- taken ----------
    async def _t_add_task(self, chat_id, title, due, notes):
        return {"task_id": self.store.add_task(title, due, notes)}

    async def _t_list_tasks(self, chat_id, include_done):
        return self.store.list_tasks(include_done) or "Geen taken."

    async def _t_complete_task(self, chat_id, task_id):
        return "Afgerond." if self.store.complete_task(task_id) else f"Taak {task_id} niet gevonden."

    async def _t_delete_task(self, chat_id, task_id):
        return "Verwijderd." if self.store.delete_task(task_id) else f"Taak {task_id} niet gevonden."

    # ---------- herinneringen ----------
    async def _t_create_reminder(self, chat_id, text, when, repeat):
        due = parse_local(when, self.tz)
        if due < datetime.now(self.tz) - timedelta(minutes=1):
            return f"Fout: {when} ligt in het verleden."
        rid = self.store.add_reminder(chat_id, text, due, repeat)
        return {"reminder_id": rid, "gepland_voor": due.strftime("%a %d-%m-%Y %H:%M"), "herhaling": repeat}

    async def _t_list_reminders(self, chat_id):
        rows = self.store.list_reminders(chat_id)
        return [
            {"id": r["id"], "tekst": r["text"], "wanneer": self._fmt_utc(r["due_at_utc"]), "herhaling": r["repeat"]}
            for r in rows
        ] or "Geen herinneringen gepland."

    async def _t_cancel_reminder(self, chat_id, reminder_id):
        ok = self.store.cancel_reminder(chat_id, reminder_id)
        return "Geannuleerd." if ok else f"Herinnering {reminder_id} niet gevonden."

    # ---------- geheugen ----------
    async def _t_remember(self, chat_id, fact):
        return {"memory_id": self.store.remember(fact)}

    async def _t_recall_memories(self, chat_id):
        return self.store.memories() or "Nog niets opgeslagen."

    async def _t_forget_memory(self, chat_id, memory_id):
        return "Vergeten." if self.store.forget(memory_id) else f"Feit {memory_id} niet gevonden."

    # ---------- Google ----------
    def _range(self, start, end):
        return parse_local(start, self.tz).isoformat(), parse_local(end, self.tz).isoformat()

    async def _t_google_calendar_list(self, chat_id, start, end):
        s, e = self._range(start, end)
        return await asyncio.to_thread(self.google.list_events, s, e) or "Geen afspraken."

    async def _t_google_calendar_create(self, chat_id, title, start, end, location, description):
        s, e = self._range(start, end)
        return await asyncio.to_thread(self.google.create_event, title, s, e, self.tz.key, location, description)

    async def _t_gmail_search(self, chat_id, query):
        return await asyncio.to_thread(self.google.search_mail, query) or "Geen e-mails gevonden."

    async def _t_gmail_read(self, chat_id, message_id):
        return await asyncio.to_thread(self.google.read_mail, message_id)

    async def _t_gmail_draft(self, chat_id, to, subject, body):
        draft_id = await asyncio.to_thread(self.google.create_draft, to, subject, body)
        return {"draft_id": draft_id, "status": "Concept opgeslagen in Gmail."}

    async def _t_gmail_send(self, chat_id, to, subject, body):
        if self.confirm is None:
            return "Fout: bevestigen is niet beschikbaar; maak in plaats daarvan een concept."
        await self.confirm(chat_id, "gmail_send", {"to": to, "subject": subject, "body": body})
        return "De gebruiker heeft een knop gekregen om het versturen te bevestigen. Nog NIET verstuurd."

    # ---------- Outlook ----------
    async def _t_outlook_calendar_list(self, chat_id, start, end):
        s, e = self._range(start, end)
        return await asyncio.to_thread(self.outlook.list_events, s, e, self.tz.key) or "Geen afspraken."

    async def _t_outlook_calendar_create(self, chat_id, title, start, end, location, description):
        # Graph verwacht lokale tijd zonder offset + tijdzonenaam.
        s = parse_local(start, self.tz).replace(tzinfo=None).isoformat()
        e = parse_local(end, self.tz).replace(tzinfo=None).isoformat()
        return await asyncio.to_thread(self.outlook.create_event, title, s, e, self.tz.key, location, description)
