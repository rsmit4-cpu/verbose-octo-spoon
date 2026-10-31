"""Kleine HTTP-ingang voor snelkoppelingen (Siri / Opdrachten, Android Tasker).

POST /ask  met header 'Authorization: Bearer <API_TOKEN>' en JSON {"text": "...", "spoken": true}
-> {"reply": "..."}. Het gesprek is hetzelfde als in WhatsApp.
"""
from __future__ import annotations

import hmac
import logging

from aiohttp import web

from .agent import Assistant

log = logging.getLogger(__name__)

SPOKEN_HINT = (
    "(Dit bericht is ingesproken via een snelkoppeling; je antwoord wordt voorgelezen. "
    "Antwoord kort, in gewone zinnen, zonder opmaak, lijstjes, emoji of links.)\n"
)


def ask_routes(assistant: Assistant, token: str, chat_id: int) -> list[web.RouteDef]:
    async def ask(request: web.Request) -> web.Response:
        auth = request.headers.get("Authorization", "")
        if not hmac.compare_digest(auth.encode(), f"Bearer {token}".encode()):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            data = await request.json()
        except ValueError:
            data = {"text": await request.text()}
        text = str(data.get("text", "")).strip()
        if not text:
            return web.json_response({"reply": "Ik heb niets gehoord. Probeer het nog eens."})
        spoken = data.get("spoken", True) not in (False, "false", "0", 0)
        try:
            reply = await assistant.chat(chat_id, (SPOKEN_HINT if spoken else "") + text)
        except Exception:
            log.exception("Fout bij /ask")
            reply = "Er ging iets mis aan mijn kant."
        return web.json_response({"reply": reply})

    return [web.post("/ask", ask)]


def build_app(assistant: Assistant, token: str, chat_id: int) -> web.Application:
    app = web.Application()
    app.add_routes(ask_routes(assistant, token, chat_id))
    return app
