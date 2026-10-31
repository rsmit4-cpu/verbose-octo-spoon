import asyncio

from aiohttp.test_utils import TestClient, TestServer

from assistant.api import SPOKEN_HINT, build_app


class FakeAssistant:
    def __init__(self):
        self.calls = []

    async def chat(self, chat_id, text):
        self.calls.append((chat_id, text))
        return "Prima, staat gepland."


def _with_client(fn):
    async def go():
        fake = FakeAssistant()
        async with TestClient(TestServer(build_app(fake, "geheim", 7))) as client:
            await fn(client, fake)
    asyncio.run(go())


def test_requires_token():
    async def t(client, fake):
        r = await client.post("/ask", json={"text": "hoi"})
        assert r.status == 401
        r = await client.post("/ask", json={"text": "hoi"}, headers={"Authorization": "Bearer fout"})
        assert r.status == 401
        assert fake.calls == []
    _with_client(t)


def test_ask_spoken_and_typed():
    async def t(client, fake):
        h = {"Authorization": "Bearer geheim"}
        r = await client.post("/ask", json={"text": "Herinner me om 9 uur"}, headers=h)
        assert (await r.json()) == {"reply": "Prima, staat gepland."}
        assert fake.calls[-1] == (7, SPOKEN_HINT + "Herinner me om 9 uur")
        await client.post("/ask", json={"text": "typen", "spoken": False}, headers=h)
        assert fake.calls[-1] == (7, "typen")
        r = await client.post("/ask", data="platte tekst", headers=h)  # zonder JSON
        assert r.status == 200 and fake.calls[-1][1].endswith("platte tekst")
    _with_client(t)
