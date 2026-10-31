"""De server: WhatsApp-webhook, herinneringen en de Siri/Tasker-ingang op één poort.

Start met `python -m assistant`.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import tempfile
from collections import deque
from pathlib import Path

from aiohttp import web

from . import api, config
from .agent import Assistant
from .db import Store
from .tools import Toolbox
from .whatsapp import REENGAGEMENT_ERROR, WhatsApp, WhatsAppError, valid_signature

log = logging.getLogger("assistant")

REMINDER_POLL_SECONDS = 20
HELP = (
    "Hoi! Ik ben je persoonlijke assistent. Stuur me gewoon een bericht of een 🎤 spraakbericht, bijvoorbeeld:\n"
    "• Herinner me morgen om 9:00 aan de tandarts\n"
    "• Wanneer speelt Feyenoord? Herinner me een kwartier van tevoren\n"
    "• Wat staat er deze week in mijn agenda?\n"
    "• Heb ik nog belangrijke ongelezen mail?\n\n"
    "*taken* – je takenlijst · *herinneringen* – gepland · *reset* – nieuw gesprek"
)
COMMANDS = {"hulp": "help", "help": "help", "start": "help", "taken": "tasks",
            "herinneringen": "reminders", "reset": "reset"}


class WhatsAppBot:
    def __init__(self, cfg: config.Config, wa: WhatsApp, store: Store, toolbox: Toolbox, assistant: Assistant):
        self.cfg, self.wa, self.store, self.toolbox, self.assistant = cfg, wa, store, toolbox, assistant
        self.pending: dict[str, tuple[int, str, dict]] = {}
        self._seen: deque[str] = deque(maxlen=500)  # Meta levert webhooks soms dubbel af
        self._tasks: set[asyncio.Task] = set()
        toolbox.confirm = self.confirm

    # ---------- bevestigen (bijv. mail versturen) ----------
    async def confirm(self, chat_id: int, kind: str, payload: dict) -> None:
        token = secrets.token_urlsafe(8)
        self.pending[token] = (chat_id, kind, payload)
        preview = f"📧 Versturen naar {payload['to']}?\n\n*Onderwerp:* {payload['subject']}\n\n{payload['body']}"
        await self.wa.send_buttons(chat_id, preview, [(f"ok:{token}", "✅ Versturen"), (f"no:{token}", "❌ Annuleren")])

    async def on_button(self, sender: int, button_id: str) -> None:
        action, _, token = button_id.partition(":")
        item = self.pending.pop(token, None)
        if item is None or item[0] != sender:
            await self.wa.send_text(sender, "Deze bevestiging is verlopen.")
            return
        _, kind, payload = item
        if action != "ok":
            await self.wa.send_text(sender, "Geannuleerd — niets verstuurd.")
            return
        if kind == "gmail_send":
            try:
                await asyncio.to_thread(self.toolbox.google.send, payload["to"], payload["subject"], payload["body"])
                await self.wa.send_text(sender, f"✅ Verstuurd naar {payload['to']}.")
            except Exception as exc:
                log.exception("Versturen mislukt")
                await self.wa.send_text(sender, f"Versturen mislukt: {exc}")

    # ---------- inkomende berichten ----------
    def handle_payload_soon(self, data: dict) -> None:
        """Webhook direct met 200 beantwoorden (anders probeert Meta opnieuw) en op de achtergrond verwerken."""
        task = asyncio.create_task(self.handle_payload(data))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def handle_payload(self, data: dict) -> None:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                for msg in change.get("value", {}).get("messages", []) or []:
                    try:
                        await self.handle_message(msg)
                    except Exception:
                        log.exception("Fout bij verwerken bericht")
                        await self.wa.send_text(int(msg["from"]), "Er ging iets mis aan mijn kant. Probeer het zo nog eens.")

    async def handle_message(self, msg: dict) -> None:
        if msg.get("id") in self._seen:
            return
        self._seen.append(msg.get("id"))
        sender = int(msg["from"])
        if sender not in self.cfg.allowed_numbers:
            log.warning("Bericht van niet-toegestaan nummer %s genegeerd (zet het in ALLOWED_NUMBERS)", sender)
            return
        await self.wa.mark_read(msg["id"])

        kind = msg.get("type")
        if kind == "text":
            await self.on_text(sender, msg["text"]["body"])
        elif kind == "audio":
            await self.on_audio(sender, msg["audio"]["id"])
        elif kind == "interactive" and msg["interactive"].get("type") == "button_reply":
            await self.on_button(sender, msg["interactive"]["button_reply"]["id"])
        elif kind == "button":  # antwoord op een sjabloonknop
            await self.on_text(sender, msg["button"].get("text", ""))
        else:
            await self.wa.send_text(sender, "Dit soort bericht kan ik (nog) niet lezen. Stuur tekst of een spraakbericht.")

    async def on_text(self, sender: int, text: str) -> None:
        command = COMMANDS.get(text.strip().lstrip("/").lower())
        if command == "help":
            await self.wa.send_text(sender, HELP)
        elif command == "tasks":
            await self.wa.send_text(sender, await self.toolbox.run("list_tasks", {"include_done": False}, sender))
        elif command == "reminders":
            await self.wa.send_text(sender, await self.toolbox.run("list_reminders", {}, sender))
        elif command == "reset":
            self.assistant.reset(sender)
            await self.wa.send_text(sender, "Nieuw gesprek gestart. (Taken, herinneringen en geheugen blijven bewaard.)")
        else:
            reply = await self.assistant.chat(sender, text)
            await self.wa.send_text(sender, reply)

    async def on_audio(self, sender: int, media_id: str) -> None:
        try:
            from .voice import transcribe

            with tempfile.TemporaryDirectory() as tmp:
                path = await self.wa.download_media(media_id, Path(tmp) / "bericht.ogg")
                text = await transcribe(str(path))
        except Exception:
            log.exception("Spraak omzetten mislukt")
            await self.wa.send_text(sender, "Ik kon je spraakbericht niet verstaan. Wil je het typen?")
            return
        if not text:
            await self.wa.send_text(sender, "Ik hoorde niets. Probeer het nog eens?")
            return
        await self.wa.send_text(sender, f"🎤 _{text}_")
        await self.on_text(sender, text)

    # ---------- herinneringen ----------
    async def send_reminder(self, r: dict) -> None:
        text = f"⏰ Herinnering: {r['text']}"
        try:
            await self.wa.send_text(r["chat_id"], text)
        except WhatsAppError as exc:
            # >24 uur geen bericht van jou gehad: WhatsApp staat dan alleen goedgekeurde sjablonen toe.
            if exc.code == REENGAGEMENT_ERROR and self.cfg.wa_reminder_template:
                await self.wa.send_template(
                    r["chat_id"], self.cfg.wa_reminder_template, self.cfg.wa_template_language, [r["text"]]
                )
            else:
                raise

    async def reminder_loop(self) -> None:
        while True:
            for r in self.store.due_reminders():
                try:
                    await self.send_reminder(r)
                except WhatsAppError:
                    log.exception("Herinnering %s kon niet worden afgeleverd; overgeslagen", r["id"])
                except Exception:
                    log.exception("Herinnering %s mislukt; volgende ronde opnieuw", r["id"])
                    continue
                self.store.mark_reminder_sent(r)
            await asyncio.sleep(REMINDER_POLL_SECONDS)


def build_web_app(cfg: config.Config, bot: WhatsAppBot) -> web.Application:
    async def verify(request: web.Request) -> web.Response:
        q = request.query
        if q.get("hub.mode") == "subscribe" and cfg.wa_verify_token and \
                secrets.compare_digest(q.get("hub.verify_token", ""), cfg.wa_verify_token):
            return web.Response(text=q.get("hub.challenge", ""))
        return web.Response(status=403)

    async def receive(request: web.Request) -> web.Response:
        body = await request.read()
        if not valid_signature(cfg.wa_app_secret, body, request.headers.get("X-Hub-Signature-256", "")):
            return web.Response(status=401)
        bot.handle_payload_soon(await request.json())
        return web.Response(text="ok")

    async def health(_: web.Request) -> web.Response:
        return web.Response(text="ok")

    app = web.Application()
    app.add_routes([web.get("/webhook", verify), web.post("/webhook", receive), web.get("/health", health)])
    if cfg.api_token and cfg.allowed_numbers:
        # De Siri/Tasker-ingang deelt het gesprek met het eerste nummer in ALLOWED_NUMBERS.
        app.add_routes(api.ask_routes(bot.assistant, cfg.api_token, cfg.allowed_numbers[0]))
    return app


def build_integrations(cfg: config.Config):
    google = outlook = None
    if cfg.google_token.exists():
        try:
            from .integrations.google import GoogleClient
            google = GoogleClient(cfg.google_token)
            log.info("Google Agenda + Gmail gekoppeld")
        except Exception:
            log.exception("Google koppelen mislukt — draai `python -m assistant.setup_google` opnieuw")
    if cfg.ms_client_id and cfg.ms_token_cache.exists():
        from .integrations.outlook import OutlookClient
        outlook = OutlookClient(cfg.ms_client_id, cfg.ms_tenant, cfg.ms_token_cache)
        log.info("Outlook-agenda gekoppeld")
    return google, outlook


def main() -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    cfg = config.load()
    missing = [n for n, v in [("WHATSAPP_TOKEN", cfg.wa_token), ("WHATSAPP_PHONE_NUMBER_ID", cfg.wa_phone_number_id),
                              ("WHATSAPP_APP_SECRET", cfg.wa_app_secret), ("WHATSAPP_VERIFY_TOKEN", cfg.wa_verify_token),
                              ("ALLOWED_NUMBERS", cfg.allowed_numbers)] if not v]
    if missing:
        raise SystemExit(f"Ontbreekt in .env: {', '.join(missing)} (zie README)")

    store = Store(cfg.db_path)
    google, outlook = build_integrations(cfg)
    toolbox = Toolbox(store=store, tz=cfg.timezone, google=google, outlook=outlook)
    assistant = Assistant(toolbox, model=cfg.model, effort=cfg.effort)
    wa = WhatsApp(cfg.wa_token, cfg.wa_phone_number_id, cfg.wa_api_version)
    bot = WhatsAppBot(cfg, wa, store, toolbox, assistant)
    app = build_web_app(cfg, bot)

    async def on_startup(_: web.Application) -> None:
        app["reminders"] = asyncio.create_task(bot.reminder_loop())

    async def on_cleanup(_: web.Application) -> None:
        app["reminders"].cancel()
        await wa.close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    log.info("Assistent draait (model %s) op poort %s. Webhook: /webhook", cfg.model, cfg.api_port)
    web.run_app(app, host=cfg.api_host, port=cfg.api_port, print=None)


if __name__ == "__main__":
    main()
