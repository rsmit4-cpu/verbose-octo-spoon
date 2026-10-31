"""Telegram-bot: de interface op je telefoon. Start met `python -m assistant.bot`."""
from __future__ import annotations

import asyncio
import logging
import secrets
import tempfile
from datetime import datetime
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters,
)

from . import config
from .agent import Assistant
from .briefing import BRIEFING_PROMPT, BriefingSettings, parse_time
from .db import Store
from .tools import Toolbox

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("assistant")

TELEGRAM_LIMIT = 4000
REMINDER_POLL_SECONDS = 20
BRIEFING_POLL_SECONDS = 30
CAPTION_LIMIT = 1000
VOICE_MODES = ("auto", "aan", "uit")


def _chunks(text: str):
    for i in range(0, len(text), TELEGRAM_LIMIT):
        yield text[i:i + TELEGRAM_LIMIT]


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
    cfg = config.load()
    if not cfg.telegram_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN ontbreekt (zie .env.example)")

    store = Store(cfg.db_path)
    google, outlook = build_integrations(cfg)
    pending: dict[str, tuple[int, str, dict]] = {}  # bevestigingen die op een tik wachten
    app = Application.builder().token(cfg.telegram_token).build()

    async def confirm(chat_id: int, kind: str, payload: dict) -> None:
        token = secrets.token_urlsafe(8)
        pending[token] = (chat_id, kind, payload)
        preview = f"📧 Versturen naar {payload['to']}?\n\nOnderwerp: {payload['subject']}\n\n{payload['body']}"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Versturen", callback_data=f"ok:{token}"),
            InlineKeyboardButton("❌ Annuleren", callback_data=f"no:{token}"),
        ]])
        await app.bot.send_message(chat_id, preview[:TELEGRAM_LIMIT], reply_markup=keyboard)

    toolbox = Toolbox(store=store, tz=cfg.timezone, google=google, outlook=outlook, confirm=confirm)
    assistant = Assistant(toolbox, model=cfg.model, effort=cfg.effort)
    briefings = BriefingSettings(store, cfg.briefing_time)

    def voice_mode(chat_id: int) -> str:
        mode = store.get_setting(chat_id, "voice_replies", cfg.voice_replies)
        return mode if mode in VOICE_MODES else "auto"

    async def send_reply(chat_id: int, text: str, as_voice: bool) -> None:
        """Antwoord als tekst, of als spraakbericht (met de tekst eronder om terug te lezen)."""
        if as_voice:
            try:
                from .voice import synthesize

                await app.bot.send_chat_action(chat_id, ChatAction.RECORD_VOICE)
                audio = await synthesize(text)
                caption = text if len(text) <= CAPTION_LIMIT else None
                await app.bot.send_voice(chat_id, audio, caption=caption)
                if caption is not None:
                    return
            except Exception:
                log.exception("Spraakbericht maken mislukt; ik stuur tekst")
        for part in _chunks(text):
            await app.bot.send_message(chat_id, part)

    def allowed(update: Update) -> bool:
        user = update.effective_user
        return bool(user) and user.id in cfg.allowed_user_ids

    async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        uid = update.effective_user.id
        if not allowed(update):
            await update.message.reply_text(
                f"Je Telegram-ID is {uid}. Zet dit in ALLOWED_USER_IDS in .env en herstart de bot."
            )
            return
        await update.message.reply_text(
            "Hoi! Ik ben je persoonlijke assistent. Stuur me gewoon een bericht, bijvoorbeeld:\n"
            "• 'Herinner me morgen om 9:00 aan de tandarts'\n"
            "• 'Wanneer speelt Feyenoord? Herinner me een kwartier van tevoren'\n"
            "• 'Wat staat er deze week in mijn agenda?'\n"
            "• 'Heb ik nog belangrijke ongelezen mail?'\n\n"
            "🎤 Je kunt ook een spraakbericht sturen (houd de microfoonknop ingedrukt); dan praat ik terug.\n"
            "☀️ Elke ochtend stuur ik je een dagoverzicht.\n\n"
            "/overzicht – dagoverzicht nu · /ochtend – tijdstip of uit · /stem – spraakantwoorden\n"
            "/taken – je takenlijst · /herinneringen – geplande herinneringen · /reset – nieuw gesprek"
        )

    async def reset(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if allowed(update):
            assistant.reset(update.effective_chat.id)
            await update.message.reply_text("Nieuw gesprek gestart. (Taken, herinneringen en geheugen blijven bewaard.)")

    async def quick(update: Update, _: ContextTypes.DEFAULT_TYPE, tool: str, args: dict) -> None:
        if allowed(update):
            out = await toolbox.run(tool, args, update.effective_chat.id)
            await update.message.reply_text(out[:TELEGRAM_LIMIT])

    async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, spoken: bool = False) -> None:
        chat_id = update.effective_chat.id
        mode = voice_mode(chat_id)
        as_voice = mode == "aan" or (mode == "auto" and spoken)
        if as_voice:
            from .voice import SPOKEN_REPLY_HINT

            text = SPOKEN_REPLY_HINT + text

        async def typing():
            while True:
                await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
                await asyncio.sleep(4)

        typer = asyncio.create_task(typing())
        try:
            reply = await assistant.chat(chat_id, text)
        except Exception:
            log.exception("Fout bij verwerken bericht")
            reply = "Er ging iets mis aan mijn kant. Probeer het zo nog eens."
        finally:
            typer.cancel()
        await send_reply(chat_id, reply, as_voice)

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if allowed(update) and update.message and update.message.text:
            await answer(update, context, update.message.text)

    async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not allowed(update) or not update.message:
            return
        media = update.message.voice or update.message.audio
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        try:
            from .voice import transcribe

            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "bericht.ogg"
                await (await media.get_file()).download_to_drive(path)
                text = await transcribe(str(path))
        except Exception:
            log.exception("Spraak omzetten mislukt")
            await update.message.reply_text("Ik kon je spraakbericht niet verstaan. Wil je het typen?")
            return
        if not text:
            await update.message.reply_text("Ik hoorde niets. Probeer het nog eens?")
            return
        await update.message.reply_text(f"🎤 “{text}”")
        await answer(update, context, text, spoken=True)

    async def on_button(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        if not allowed(update):
            return
        action, _, token = (query.data or "").partition(":")
        item = pending.pop(token, None)
        if item is None:
            await query.edit_message_text("Deze bevestiging is verlopen.")
            return
        chat_id, kind, payload = item
        if action != "ok":
            await query.edit_message_text("Geannuleerd — niets verstuurd.")
            return
        if kind == "gmail_send":
            try:
                await asyncio.to_thread(google.send, payload["to"], payload["subject"], payload["body"])
                await query.edit_message_text(f"✅ Verstuurd naar {payload['to']}.")
            except Exception as exc:
                log.exception("Versturen mislukt")
                await query.edit_message_text(f"Versturen mislukt: {exc}")

    async def stem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not allowed(update):
            return
        chat_id = update.effective_chat.id
        arg = (context.args[0].lower() if context.args else "")
        if arg in VOICE_MODES:
            store.set_setting(chat_id, "voice_replies", arg)
        uitleg = {"auto": "ik praat terug als jij een spraakbericht stuurt",
                  "aan": "ik antwoord altijd met een spraakbericht", "uit": "ik antwoord altijd met tekst"}
        await update.message.reply_text(
            f"Spraakantwoorden: *{voice_mode(chat_id)}* — {uitleg[voice_mode(chat_id)]}.\n"
            "Wijzigen: /stem auto · /stem aan · /stem uit", parse_mode="Markdown")

    async def send_briefing(chat_id: int) -> None:
        await app.bot.send_chat_action(chat_id, ChatAction.TYPING)
        try:
            text = await assistant.chat(chat_id, BRIEFING_PROMPT)
        except Exception:
            log.exception("Ochtendoverzicht maken mislukt")
            await app.bot.send_message(chat_id, "☀️ Goedemorgen! Het lukte me niet om je overzicht te maken. "
                                                "Stuur /overzicht om het opnieuw te proberen.")
            return
        await send_reply(chat_id, text, briefings.voice(chat_id))

    async def overzicht(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if allowed(update):
            await send_briefing(update.effective_chat.id)

    async def ochtend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not allowed(update):
            return
        chat_id = update.effective_chat.id
        args = [a.lower() for a in context.args or []]
        if args[:1] == ["uit"]:
            briefings.set_time(chat_id, None)
        elif args[:1] == ["stem"] and args[1:2] in (["aan"], ["uit"]):
            briefings.set_voice(chat_id, args[1] == "aan")
        elif args:
            at = parse_time(args[0])
            if at is None:
                await update.message.reply_text("Dat tijdstip snap ik niet. Probeer bijv. /ochtend 7:15")
                return
            briefings.set_time(chat_id, at)
        at = briefings.time_for(chat_id)
        status = f"elke dag om {at.strftime('%H:%M')}" if at else "uit"
        voice = "aan" if briefings.voice(chat_id) else "uit"
        await update.message.reply_text(
            f"☀️ Ochtendoverzicht: {status} (voorlezen: {voice}).\n"
            "Wijzigen: /ochtend 7:00 · /ochtend uit · /ochtend stem aan · /ochtend stem uit\n"
            "Nu een overzicht: /overzicht")

    async def briefing_loop() -> None:
        while True:
            try:
                now = datetime.now(cfg.timezone)
                # In een privéchat is de chat-ID gelijk aan je gebruikers-ID.
                for chat_id in sorted(cfg.allowed_user_ids):
                    if briefings.due(chat_id, now):
                        briefings.mark_sent(chat_id, now.date())  # eerst markeren: nooit dubbel sturen
                        await send_briefing(chat_id)
            except Exception:
                log.exception("Fout in ochtendoverzicht-lus")
            await asyncio.sleep(BRIEFING_POLL_SECONDS)

    async def reminder_loop() -> None:
        while True:
            try:
                for r in store.due_reminders():
                    await app.bot.send_message(r["chat_id"], f"⏰ Herinnering: {r['text']}")
                    store.mark_reminder_sent(r)
            except Exception:
                log.exception("Fout in herinneringslus")
            await asyncio.sleep(REMINDER_POLL_SECONDS)

    async def post_init(application: Application) -> None:
        application.bot_data["reminder_task"] = asyncio.create_task(reminder_loop())
        application.bot_data["briefing_task"] = asyncio.create_task(briefing_loop())
        if cfg.api_token:
            from . import api

            # In een privéchat is de chat-ID gelijk aan je gebruikers-ID: zo deel je één gesprek met Telegram.
            owner = min(cfg.allowed_user_ids) if cfg.allowed_user_ids else None
            if owner is None:
                log.warning("API_TOKEN gezet maar ALLOWED_USER_IDS is leeg: snelkoppeling-API niet gestart.")
            else:
                application.bot_data["api"] = await api.start(
                    assistant, cfg.api_token, owner, cfg.api_host, cfg.api_port
                )

    async def post_shutdown(application: Application) -> None:
        if runner := application.bot_data.get("api"):
            await runner.cleanup()

    app.post_init = post_init
    app.post_shutdown = post_shutdown
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("stem", stem))
    app.add_handler(CommandHandler("overzicht", overzicht))
    app.add_handler(CommandHandler("ochtend", ochtend))
    app.add_handler(CommandHandler("taken", lambda u, c: quick(u, c, "list_tasks", {"include_done": False})))
    app.add_handler(CommandHandler("herinneringen", lambda u, c: quick(u, c, "list_reminders", {})))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))

    if not cfg.allowed_user_ids:
        log.warning("ALLOWED_USER_IDS is leeg: niemand kan de bot gebruiken. Stuur /start om je ID te zien.")
    log.info("Assistent draait (model %s). Stop met Ctrl+C.", cfg.model)
    app.run_polling()


if __name__ == "__main__":
    main()
