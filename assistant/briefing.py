"""Het dagelijkse ochtendoverzicht."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from .db import Store

DEFAULT_TIME = "07:30"
CATCH_UP = timedelta(hours=2)  # stond de computer uit? Tot 2 uur na het tijdstip alsnog sturen, daarna niet meer.

BRIEFING_PROMPT = """\
[Automatisch ochtendoverzicht — de gebruiker heeft hier niet zelf om gevraagd, dit is zijn/haar dagelijkse briefing.]
Stel mijn dagoverzicht voor vandaag samen. Haal eerst recall_memories op voor persoonlijke context (woonplaats,
favoriete club, enz.). Gebruik daarna de tools die beschikbaar zijn:
• Agenda('s): afspraken van vandaag (en noem het als er morgenvroeg iets vroegs staat).
• Taken: wat openstaat, met wat vandaag of eerder af moest bovenaan.
• Herinneringen die vandaag afgaan.
• Mail (als Gmail gekoppeld is): alleen echt belangrijke of dringende ongelezen mail van de laatste dag, max. 3.
• Het weer van vandaag in mijn woonplaats (web_search). Weet je mijn woonplaats niet, sla het weer over en vraag
  er onderaan één keer naar.
• Speelt mijn favoriete club vandaag of morgen? Zo ja: noem de aftraptijd en bied een herinnering aan.
Begin met een korte, vriendelijke groet. Houd het overzichtelijk en kort (het wordt op een telefoon gelezen);
sla onderdelen zonder inhoud over in plaats van "geen" te melden. Eindig met één nuttige tip of vraag voor vandaag.
"""


def parse_time(value: str) -> time | None:
    """'7:30', '07.30', '730' of '7' -> time; ongeldig -> None."""
    m = re.fullmatch(r"\s*(\d{1,2})(?:[:.h]?(\d{2}))?\s*(?:uur)?\s*", value)
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    return time(hour, minute) if hour < 24 and minute < 60 else None


def is_due(now_local: datetime, at: time, last_sent: date | None) -> bool:
    if last_sent == now_local.date():
        return False
    scheduled = now_local.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    return scheduled <= now_local < scheduled + CATCH_UP


class BriefingSettings:
    """Per chat: tijdstip (of 'uit'), laatst verstuurde datum, en of hij ook voorgelezen wordt."""

    def __init__(self, store: Store, default_time: str = DEFAULT_TIME):
        self.store = store
        self.default_time = default_time

    def time_for(self, chat_id: int) -> time | None:
        value = self.store.get_setting(chat_id, "briefing_time", self.default_time)
        return None if value in (None, "", "uit") else parse_time(value)

    def set_time(self, chat_id: int, at: time | None) -> None:
        self.store.set_setting(chat_id, "briefing_time", at.strftime("%H:%M") if at else "uit")

    def voice(self, chat_id: int) -> bool:
        return self.store.get_setting(chat_id, "briefing_voice", "uit") == "aan"

    def set_voice(self, chat_id: int, on: bool) -> None:
        self.store.set_setting(chat_id, "briefing_voice", "aan" if on else "uit")

    def last_sent(self, chat_id: int) -> date | None:
        value = self.store.get_setting(chat_id, "briefing_last")
        return date.fromisoformat(value) if value else None

    def mark_sent(self, chat_id: int, day: date) -> None:
        self.store.set_setting(chat_id, "briefing_last", day.isoformat())

    def due(self, chat_id: int, now_local: datetime) -> bool:
        at = self.time_for(chat_id)
        return at is not None and is_due(now_local, at, self.last_sent(chat_id))
