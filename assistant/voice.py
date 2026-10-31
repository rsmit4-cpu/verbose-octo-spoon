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


# ---------- tekst naar spraak ----------
SPOKEN_REPLY_HINT = (
    "(De gebruiker sprak dit in en krijgt je antwoord als spraakbericht. Antwoord kort, in gewone spreektaal, "
    "zonder opmaak, lijstjes, emoji of links.)\n"
)
# Natuurlijke Nederlandse stemmen via edge-tts (gratis, geen sleutel). Andere opties: nl-NL-MaartenNeural,
# nl-NL-FennaNeural, nl-BE-DenaNeural, nl-BE-ArnaudNeural.
MAX_SPOKEN_CHARS = 3000


def _strip_for_speech(text: str) -> str:
    import re

    text = re.sub(r"https?://\S+", "", text)          # links niet voorlezen
    text = re.sub(r"[*_`#>|]+", "", text)              # opmaaktekens
    return re.sub(r"\s+\n", "\n", text).strip()[:MAX_SPOKEN_CHARS]


def to_ogg_opus(audio: bytes) -> bytes:
    """Willekeurig audioformaat (bijv. mp3) -> OGG/Opus, het formaat van Telegram-spraakberichten."""
    import io

    import av

    src = av.open(io.BytesIO(audio))
    buf = io.BytesIO()
    dst = av.open(buf, "w", format="ogg")
    stream = dst.add_stream("libopus", rate=48000, layout="mono")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
    for frame in src.decode(audio=0):
        for f in resampler.resample(frame):
            for packet in stream.encode(f):
                dst.mux(packet)
    for f in resampler.resample(None):
        for packet in stream.encode(f):
            dst.mux(packet)
    for packet in stream.encode(None):
        dst.mux(packet)
    dst.close()
    src.close()
    return buf.getvalue()


async def synthesize(text: str) -> bytes:
    """Tekst -> OGG/Opus-spraakbericht."""
    import edge_tts

    voice = os.getenv("TTS_VOICE", "nl-NL-ColetteNeural")
    mp3 = bytearray()
    async for chunk in edge_tts.Communicate(_strip_for_speech(text), voice).stream():
        if chunk["type"] == "audio":
            mp3 += chunk["data"]
    if not mp3:
        raise RuntimeError("Geen audio ontvangen van de spraakdienst")
    return await asyncio.to_thread(to_ogg_opus, bytes(mp3))
