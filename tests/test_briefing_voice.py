from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from assistant.briefing import BriefingSettings, is_due, parse_time
from assistant.db import Store
from assistant.voice import _strip_for_speech

TZ = ZoneInfo("Europe/Amsterdam")


@pytest.mark.parametrize("raw,expected", [
    ("7:30", time(7, 30)), ("07.15", time(7, 15)), ("730", time(7, 30)), ("7", time(7, 0)),
    ("8 uur", time(8, 0)), ("25:00", None), ("7:75", None), ("vroeg", None),
])
def test_parse_time(raw, expected):
    assert parse_time(raw) == expected


def test_is_due_window_and_once_per_day():
    at = time(7, 30)
    d = lambda h, m: datetime(2026, 11, 2, h, m, tzinfo=TZ)
    assert not is_due(d(7, 29), at, None)
    assert is_due(d(7, 30), at, None)
    assert is_due(d(9, 0), at, None)            # computer stond even uit: alsnog
    assert not is_due(d(10, 0), at, None)       # te laat: niet 's middags nog een ochtendoverzicht
    assert not is_due(d(7, 45), at, date(2026, 11, 2))  # vandaag al gestuurd


def test_settings(tmp_path):
    b = BriefingSettings(Store(tmp_path / "t.db"), "07:30")
    now = datetime(2026, 11, 2, 7, 31, tzinfo=TZ)
    assert b.time_for(1) == time(7, 30) and b.due(1, now)
    b.mark_sent(1, now.date())
    assert not b.due(1, now)
    b.set_time(2, None)
    assert b.time_for(2) is None and not b.due(2, now)
    b.set_time(2, time(6, 45))
    assert b.time_for(2) == time(6, 45)
    assert not b.voice(1)
    b.set_voice(1, True)
    assert b.voice(1)


def test_default_off(tmp_path):
    b = BriefingSettings(Store(tmp_path / "t.db"), "uit")
    assert b.time_for(1) is None


def test_strip_for_speech():
    assert _strip_for_speech("*Let op*: zie https://voorbeeld.nl/x _morgen_") == "Let op: zie  morgen"
