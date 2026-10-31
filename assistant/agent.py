"""Het brein: een Claude-agentlus met tools, per WhatsApp-nummer een eigen gesprek."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import anthropic

from .tools import Toolbox

log = logging.getLogger(__name__)

MAX_ITERATIONS = 15
BETAS = [
    "server-side-fallback-2026-07-01",  # bij een (onterechte) weigering automatisch een ander model
    "compact-2026-01-12",               # lange gesprekken worden server-side samengevat
]

SYSTEM_PROMPT = """\
Je bent de persoonlijke assistent van de gebruiker. Je praat met hem/haar via WhatsApp op de telefoon.
Antwoord standaard in het Nederlands (of in de taal van de gebruiker), kort en to the point: het zijn chatberichten
op een klein scherm. Gebruik WhatsApp-opmaak: *vet* (één sterretje), _cursief_, en '• ' voor lijstjes.
Geen markdown-koppen (#), geen **dubbele sterretjes** en geen tabellen.

Wat je doet:
- Meedenken: plannen maken, opties afwegen, dingen uitzoeken. Gebruik web_search voor actuele informatie.
- Taken en to-do's bijhouden met de taak-tools.
- Herinneringen plannen met create_reminder; die komen als pushbericht op de telefoon binnen. Voor sport
  (bijv. een voetbalwedstrijd): zoek eerst de exacte aftraptijd op via web_search, reken om naar de lokale tijdzone,
  en plan de herinnering standaard 15 minuten van tevoren tenzij de gebruiker iets anders vraagt. Noem de bron/tijd.
- Agenda's: Google Agenda en/of Outlook, als die tools beschikbaar zijn. Vraag bij twijfel in welke agenda.
- Gmail: zoeken, lezen, concepten maken. Versturen gaat via gmail_send, waarna de gebruiker zelf op een knop tikt.
- Onthouden: sla blijvende feiten over de gebruiker op met remember (favoriete club, namen, voorkeuren). Haal ze op
  met recall_memories zodra persoonlijke context kan helpen, bijvoorbeeld aan het begin van een gesprek.

Tijden: elk gebruikersbericht begint met de huidige lokale datum en tijd. Gebruik die voor 'morgen', 'vanavond', enz.
Geef tijden aan tools altijd als lokale tijd (YYYY-MM-DDTHH:MM).

Grenzen — wees hier eerlijk over:
- Je draait op een server, niet op de telefoon. Je kunt GEEN telefooninstellingen wijzigen (wifi, helderheid,
  niet storen, enz.) en GEEN bestanden of opslag op de telefoon beheren. Geef in plaats daarvan concrete stappen
  voor iPhone of Android, of stel een Opdrachten-automatisering (iOS) / Routine (Android) voor die het voortaan doet.
  Vraag welk toestel de gebruiker heeft als dat nog niet bekend is (en onthoud het).
- Verzin geen agenda-items, e-mails of tijden. Als een tool faalt, zeg dat.
- Doe niets onomkeerbaars (mail versturen, iets verwijderen) zonder dat de gebruiker erom vroeg.
"""


class Assistant:
    def __init__(self, toolbox: Toolbox, model: str, effort: str, client: anthropic.AsyncAnthropic | None = None):
        self.client = client or anthropic.AsyncAnthropic()
        self.toolbox = toolbox
        self.model = model
        self.effort = effort
        self._history: dict[int, list] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def reset(self, chat_id: int) -> None:
        self._history.pop(chat_id, None)

    async def _call(self, messages: list):
        return await self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=self.toolbox.definitions(),
            messages=messages,
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
            context_management={"edits": [{"type": "compact_20260112"}]},
            fallbacks="default",
            betas=BETAS,
        )

    async def chat(self, chat_id: int, text: str) -> str:
        lock = self._locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            # Alleen achteraan toevoegen (append-only): de geschiedenis wordt nooit herschreven.
            messages = self._history.setdefault(chat_id, [])
            now = datetime.now(self.toolbox.tz).strftime("%A %d-%m-%Y %H:%M (%Z)")
            messages.append({"role": "user", "content": f"[Huidige tijd: {now}]\n{text}"})
            return await self._loop(chat_id, messages)

    async def _loop(self, chat_id: int, messages: list) -> str:
        texts: list[str] = []
        for _ in range(MAX_ITERATIONS):
            response = await self._call(messages)
            # Volledige content teruggeven (ook thinking-, compaction- en fallback-blokken).
            messages.append({"role": "assistant", "content": response.content})
            # Met web_search is het antwoord opgesplitst in meerdere tekstblokken (citaten): samenvoegen.
            turn_text = "".join(b.text for b in response.content if b.type == "text").strip()
            if turn_text:
                texts.append(turn_text)

            if response.stop_reason == "refusal":
                return "Sorry, daar kan ik je niet mee helpen."
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason == "max_tokens":
                texts.append("(Mijn antwoord werd afgekapt — vraag gerust om de rest.)")
                break

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                break

            results = await asyncio.gather(*(self._run_tool(chat_id, b) for b in tool_uses))
            messages.append({"role": "user", "content": list(results)})
        else:
            texts.append("(Ik ben gestopt na te veel stappen.)")

        return texts[-1] if texts else "Klaar."

    async def _run_tool(self, chat_id: int, block) -> dict:
        try:
            output = await self.toolbox.run(block.name, dict(block.input), chat_id)
            return {"type": "tool_result", "tool_use_id": block.id, "content": output}
        except Exception as exc:  # tool-fouten teruggeven aan Claude i.p.v. crashen
            log.exception("Tool %s faalde", block.name)
            return {"type": "tool_result", "tool_use_id": block.id, "content": f"Fout: {exc}", "is_error": True}
