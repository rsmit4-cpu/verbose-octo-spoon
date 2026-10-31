"""Telegram-bot: de interface op je telefoon. Start met `python -m assistant.bot`."""
from __future__ import annotations

import asyncio
import logging
import secrets

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters,
)

from . import config
from .agent import Assistant
from .db import Store
from .tools import Toolbox

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("assistant")

TELEGRAM_LIMIT = 4000
REMINDER_POLL_SECONDS = 20


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

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not allowed(update) or not update.message or not update.message.text:
            return
        chat_id = update.effective_chat.id

        async def typing():
            while True:
                await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
                await asyncio.sleep(4)

        typer = asyncio.create_task(typing())
        try:
            reply = await assistant.chat(chat_id, update.message.text)
        except Exception:
            log.exception("Fout bij verwerken bericht")
            reply = "Er ging iets mis aan mijn kant. Probeer het zo nog eens."
        finally:
            typer.cancel()
        for part in _chunks(reply):
            await update.message.reply_text(part)

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

    app.post_init = post_init
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("taken", lambda u, c: quick(u, c, "list_tasks", {"include_done": False})))
    app.add_handler(CommandHandler("herinneringen", lambda u, c: quick(u, c, "list_reminders", {})))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    if not cfg.allowed_user_ids:
        log.warning("ALLOWED_USER_IDS is leeg: niemand kan de bot gebruiken. Stuur /start om je ID te zien.")
    log.info("Assistent draait (model %s). Stop met Ctrl+C.", cfg.model)
    app.run_polling()


if __name__ == "__main__":
    main()
