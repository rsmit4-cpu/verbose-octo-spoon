import asyncio
import hashlib
import hmac
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from aiohttp.test_utils import TestClient, TestServer

from assistant import config
from assistant.db import Store
from assistant.server import WhatsAppBot, build_web_app
from assistant.tools import Toolbox
from assistant.whatsapp import REENGAGEMENT_ERROR, WhatsAppError, valid_signature

ME = 31612345678


class FakeWA:
    def __init__(self, fail_text_with=None):
        self.sent = []
        self.fail_text_with = fail_text_with

    async def send_text(self, to, text):
        if self.fail_text_with:
            raise WhatsAppError(400, {"error": {"code": self.fail_text_with, "message": "re-engagement"}})
        self.sent.append(("text", int(to), text))

    async def send_buttons(self, to, body, buttons):
        self.sent.append(("buttons", int(to), body, buttons))

    async def send_template(self, to, name, language, params):
        self.sent.append(("template", int(to), name, params))

    async def mark_read(self, message_id):
        pass


class FakeAssistant:
    def __init__(self):
        self.calls = []

    async def chat(self, chat_id, text):
        self.calls.append((chat_id, text))
        return f"antwoord op: {text}"

    def reset(self, chat_id):
        self.calls.append((chat_id, "<reset>"))


class FakeGoogle:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body):
        self.sent.append((to, subject, body))


@pytest.fixture
def setup(tmp_path):
    cfg = replace(config.Config(), allowed_numbers=(ME,), wa_app_secret="appgeheim", wa_verify_token="verify",
                  api_token="", data_dir=tmp_path)
    store = Store(tmp_path / "t.db")
    toolbox = Toolbox(store=store, tz=ZoneInfo("Europe/Amsterdam"), google=FakeGoogle())
    wa, assistant = FakeWA(), FakeAssistant()
    return cfg, store, toolbox, wa, assistant, WhatsAppBot(cfg, wa, store, toolbox, assistant)


def msg(kind="text", sender=ME, mid="m1", **body):
    m = {"from": str(sender), "id": mid, "type": kind}
    m.update(body or {"text": {"body": "hallo"}})
    return {"entry": [{"changes": [{"value": {"messages": [m]}}]}]}


def run(c):
    return asyncio.run(c)


def test_signature():
    body = b'{"a":1}'
    sig = "sha256=" + hmac.new(b"geheim", body, hashlib.sha256).hexdigest()
    assert valid_signature("geheim", body, sig)
    assert not valid_signature("geheim", body, "sha256=fout")
    assert not valid_signature("geheim", body, "")


def test_text_goes_to_assistant_and_dedupes(setup):
    *_, wa, assistant, bot = setup
    run(bot.handle_payload(msg()))
    run(bot.handle_payload(msg()))  # dubbele aflevering door Meta
    assert assistant.calls == [(ME, "hallo")]
    assert wa.sent == [("text", ME, "antwoord op: hallo")]


def test_unknown_number_ignored(setup):
    *_, wa, assistant, bot = setup
    run(bot.handle_payload(msg(sender=31699999999)))
    assert assistant.calls == [] and wa.sent == []


def test_commands(setup):
    _, store, *_, wa, assistant, bot = setup
    store.add_task("Bellen", None, None)
    run(bot.handle_payload(msg(mid="a", text={"body": "Taken"})))
    run(bot.handle_payload(msg(mid="b", text={"body": "/reset"})))
    assert "Bellen" in wa.sent[0][2]
    assert assistant.calls == [(ME, "<reset>")]


def test_voice_message(setup, monkeypatch):
    *_, wa, assistant, bot = setup

    async def fake_download(media_id, dest):
        dest.write_bytes(b"ogg")
        return dest

    async def fake_transcribe(path):
        return "zet bellen op mijn lijst"

    wa.download_media = fake_download
    monkeypatch.setattr("assistant.voice.transcribe", fake_transcribe)
    run(bot.handle_payload(msg(kind="audio", audio={"id": "media1"})))
    assert assistant.calls == [(ME, "zet bellen op mijn lijst")]
    assert wa.sent[0] == ("text", ME, "🎤 _zet bellen op mijn lijst_")


def test_mail_confirmation_flow(setup):
    _, _, toolbox, wa, _, bot = setup
    run(toolbox.run("gmail_send", {"to": "jan@x.nl", "subject": "Hoi", "body": "Tot morgen"}, ME))
    kind, to, body, buttons = wa.sent[0]
    assert kind == "buttons" and "jan@x.nl" in body and len(buttons) == 2
    assert toolbox.google.sent == []  # nog niet verstuurd
    ok_id = buttons[0][0]
    run(bot.handle_payload(msg(kind="interactive", mid="c",
                               interactive={"type": "button_reply", "button_reply": {"id": ok_id}})))
    assert toolbox.google.sent == [("jan@x.nl", "Hoi", "Tot morgen")]
    run(bot.handle_payload(msg(kind="interactive", mid="d",
                               interactive={"type": "button_reply", "button_reply": {"id": ok_id}})))
    assert len(toolbox.google.sent) == 1  # tweede tik doet niets


def test_reminder_falls_back_to_template(setup):
    cfg, store, toolbox, _, assistant, _ = setup
    wa = FakeWA(fail_text_with=REENGAGEMENT_ERROR)
    bot = WhatsAppBot(replace(cfg, wa_reminder_template="herinnering"), wa, store, toolbox, assistant)
    run(bot.send_reminder({"chat_id": ME, "text": "Aftrap PSV"}))
    assert wa.sent == [("template", ME, "herinnering", ["Aftrap PSV"])]
    bot_no_template = WhatsAppBot(cfg, wa, store, toolbox, assistant)
    with pytest.raises(WhatsAppError):
        run(bot_no_template.send_reminder({"chat_id": ME, "text": "x"}))


def test_webhook_http(setup):
    cfg, *_, assistant, bot = setup

    async def go():
        async with TestClient(TestServer(build_web_app(cfg, bot))) as client:
            r = await client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify",
                                                     "hub.challenge": "1234"})
            assert r.status == 200 and await r.text() == "1234"
            r = await client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "fout"})
            assert r.status == 403
            body = json.dumps(msg()).encode()
            r = await client.post("/webhook", data=body, headers={"X-Hub-Signature-256": "sha256=fout"})
            assert r.status == 401
            sig = "sha256=" + hmac.new(b"appgeheim", body, hashlib.sha256).hexdigest()
            r = await client.post("/webhook", data=body, headers={"X-Hub-Signature-256": sig,
                                                                   "Content-Type": "application/json"})
            assert r.status == 200
            await asyncio.sleep(0.05)
            assert assistant.calls == [(ME, "hallo")]
    run(go())
