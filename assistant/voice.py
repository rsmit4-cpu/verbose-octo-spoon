"""Spraak naar tekst, lokaal en gratis met faster-whisper (geen extra API-sleutel nodig).

Het model wordt bij het eerste spraakbericht eenmalig gedownload (~500 MB voor 'small').
"""
from __future__ import annotations

import asyncio
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel

    size = os.getenv("WHISPER_MODEL", "small")  # tiny / base / small / medium
    return WhisperModel(size, device="cpu", compute_type="int8")


def _transcribe(path: str) -> str:
    language = os.getenv("WHISPER_LANGUAGE") or None  # leeg = automatisch herkennen
    segments, _ = _model().transcribe(path, language=language, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


async def transcribe(path: str) -> str:
    return await asyncio.to_thread(_transcribe, path)
