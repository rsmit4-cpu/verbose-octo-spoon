import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

from assistant.agent import Assistant
from assistant.db import Store
from assistant.tools import Toolbox, parse_local

TZ = ZoneInfo("Europe/Amsterdam")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "t.db")


def run(coro):
    return asyncio.run(coro)


def test_tasks(store):
    tid = store.add_task("Boodschappen", None, None)
    assert [t["title"] for t in store.list_tasks()] == ["Boodschappen"]
    assert store.complete_task(tid)
    assert store.list_tasks() == []
    assert len(store.list_tasks(include_done=True)) == 1


def test_reminders_once_and_repeat(store):
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    once = store.add_reminder(1, "eenmalig", past)
    daily = store.add_reminder(1, "dagelijks", past, "daily")
    due = store.due_reminders()
    assert {r["id"] for r in due} == {once, daily}
    for r in due:
        store.mark_reminder_sent(r)
    assert store.due_reminders() == []
    remaining = store.list_reminders(1)
    assert [r["id"] for r in remaining] == [daily]
    assert datetime.fromisoformat(remaining[0]["due_at_utc"]) > datetime.now(timezone.utc)


def test_parse_local_uses_timezone():
    dt = parse_local("2026-11-02T20:00", TZ)
    assert dt.utcoffset() == timedelta(hours=1)  # wintertijd
    assert parse_local("2026-07-02T20:00+00:00", TZ).utcoffset() == timedelta(0)


def test_toolbox_reminder_rejects_past(store):
    tb = Toolbox(store=store, tz=TZ)
    out = run(tb.run("create_reminder", {"text": "x", "when": "2000-01-01T10:00", "repeat": "none"}, 1))
    assert out.startswith("Fout")
    future = (datetime.now(TZ) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
    out = run(tb.run("create_reminder", {"text": "Wedstrijd", "when": future, "repeat": "none"}, 1))
    assert "reminder_id" in out
    assert "Wedstrijd" in run(tb.run("list_reminders", {}, 1))


def test_tool_definitions_depend_on_integrations(store):
    names = lambda tb: [t["name"] for t in tb.definitions()]
    base = names(Toolbox(store=store, tz=TZ))
    assert "gmail_search" not in base and base[-1] == "web_search"
    full = names(Toolbox(store=store, tz=TZ, google=object(), outlook=object()))
    assert {"gmail_send", "google_calendar_create", "outlook_calendar_list"} <= set(full)
    for t in Toolbox(store=store, tz=TZ, google=object(), outlook=object()).definitions():
        if "input_schema" in t:
            schema = t["input_schema"]
            assert set(schema["required"]) == set(schema["properties"])  # strict-modus eis


class FakeMessages:
    """Simuleert Claude: eerst een tool-aanroep, dan een antwoord."""

    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return NS(stop_reason="tool_use", content=[
                NS(type="text", text="Even vastleggen."),
                NS(type="tool_use", id="tu_1", name="add_task", input={"title": "Bellen", "due": None, "notes": None}),
            ])
        return NS(stop_reason="end_turn", content=[NS(type="text", text="Staat erop: "), NS(type="text", text="Bellen.")])


def test_agent_loop_runs_tools_and_appends_only(store):
    fake = FakeMessages()
    client = NS(beta=NS(messages=fake))
    a = Assistant(Toolbox(store=store, tz=TZ), model="claude-opus-5-5", effort="medium", client=client)
    reply = run(a.chat(42, "Zet bellen op mijn lijst"))
    assert reply == "Staat erop: Bellen."
    assert store.list_tasks()[0]["title"] == "Bellen"
    second = fake.calls[1]
    msgs = second["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    assert msgs[2]["content"][0]["tool_use_id"] == "tu_1"
    assert second["fallbacks"] == "default"
    assert "thinking" not in second and second["output_config"] == {"effort": "medium"}
