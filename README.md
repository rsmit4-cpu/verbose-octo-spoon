# Persoonlijke assistent (Telegram + Claude)

Een persoonlijke assistent die je via **Telegram op je telefoon** gebruikt. Claude is het brein; de bot
kan meedenken, dingen opzoeken, taken bijhouden, herinneringen als pushbericht sturen en je
Google Agenda, Gmail en Outlook-agenda gebruiken.

## Wat kan hij?

| Functie | Voorbeeld |
|---|---|
| Meedenken & web zoeken | "Help me een weekendje Gent plannen" · "Wat is het weer zaterdag?" |
| Herinneringen (push) | "Herinner me morgen om 9:00 aan de tandarts" · "Elke maandag 8:00 aan de kliko" |
| Sportwedstrijden | "Wanneer speelt Ajax? Herinner me een kwartier van tevoren" (zoekt de aftrap op) |
| Taken / to-do's | "Zet 'verzekering opzeggen' op mijn lijst" · `/taken` |
| Geheugen | "Onthoud dat ik een iPhone heb en fan ben van PSV" |
| Google Agenda | "Wat staat er deze week in mijn agenda?" · "Zet vrijdag 14:00 een afspraak met Sanne" |
| Outlook-agenda | Zelfde als hierboven, in je Outlook-/werkagenda |
| Gmail | "Heb ik belangrijke ongelezen mail?" · "Schrijf een antwoord aan Jan" (versturen pas na jouw tik op ✅) |

### Wat hij (nog) níet kan: je telefoon besturen

De assistent draait op een computer/server, niet óp je telefoon. iPhone en Android laten een app van
buitenaf geen **instellingen wijzigen** of **opslag/bestanden beheren**. Wat hij wel doet: je precies
vertellen welke stappen je moet nemen, of een automatisering voorstellen die het voortaan voor je doet:

- **iPhone:** app *Opdrachten* → *Automatisering* (bijv. "om 23:00 → Niet storen aan, helderheid 30%").
  Opslag: *Instellingen → Algemeen → iPhone-opslag* (met aanbevelingen zoals "Ongebruikte apps verwijderen").
- **Android:** *Routines* (Samsung: *Modi en routines*) of de app *Tasker*.
  Opslag: *Files by Google* → *Opschonen*.

Wil je dat de assistent dit later wél zelf kan, dan is de volgende stap een kleine companion-app of
een Tasker/Opdrachten-koppeling. Zeg het maar.

## Installatie

Je hebt nodig: Python 3.10+, een computer die aan blijft staan (of een kleine server/Raspberry Pi),
een **Anthropic API-sleutel** (<https://console.anthropic.com>) en een **Telegram-bot**.

```bash
git clone <deze repo> && cd verbose-octo-spoon
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # en vul de waarden in
```

1. **Telegram-bot maken:** open Telegram, zoek `@BotFather`, stuur `/newbot` en kopieer het token naar
   `TELEGRAM_BOT_TOKEN` in `.env`.
2. **Starten:** `python -m assistant.bot`
3. **Jezelf toegang geven:** stuur `/start` naar je bot. Hij antwoordt met je Telegram-ID. Zet dat in
   `ALLOWED_USER_IDS` in `.env` en herstart. (Alleen jij kunt de bot dan gebruiken — belangrijk, want
   hij heeft toegang tot je mail en agenda.)

### Google Agenda + Gmail koppelen (optioneel)

1. Ga naar <https://console.cloud.google.com>, maak een project en schakel de **Google Calendar API** en
   **Gmail API** in.
2. *APIs en services → OAuth-toestemmingsscherm*: type *Extern*, voeg jezelf toe als testgebruiker.
3. *Inloggegevens → OAuth-client-ID → Desktop-app*, download het JSON-bestand naar
   `data/google_credentials.json`.
4. `python -m assistant.setup_google` (opent je browser) en herstart de bot.

### Outlook-agenda koppelen (optioneel)

1. Ga naar <https://entra.microsoft.com> → *App-registraties → Nieuwe registratie*. Kies
   persoonlijke Microsoft-accounts (outlook.com/hotmail) en/of je organisatie.
2. Onder *Verificatie*: *Openbare clientstromen toestaan* → **Ja**.
3. Zet de *Application (client) ID* in `.env` als `MS_CLIENT_ID`
   (`MS_TENANT=consumers` voor privé, `organizations` voor werk).
4. `python -m assistant.setup_outlook` en volg de instructies; herstart de bot.

## Snel aanroepen: met je stem of door te typen

### 1. In Telegram (werkt direct)
- **Typen:** gewoon een bericht sturen.
- **Spreken:** houd de 🎤-knop ingedrukt en spreek een spraakbericht in. De bot zet het lokaal en gratis
  om naar tekst (faster-whisper; de eerste keer wordt het spraakmodel eenmalig gedownload, ~500 MB) en laat
  zien wat hij verstond.
- **Sneller openen:** zet de chat vast bovenaan in Telegram. Op Android: chat openen → ⋮ →
  *Toevoegen aan beginscherm*.

### 2. "Hé Siri, Assistent" (zonder Telegram te openen)
Hiermee spreek je in of typ je, en het antwoord wordt **voorgelezen**. Het is hetzelfde gesprek als in Telegram.

**Eenmalig op de server:**
1. Maak een geheime sleutel: `python -c "import secrets; print(secrets.token_urlsafe(32))"` en zet die
   in `.env` als `API_TOKEN`. Herstart de bot.
2. Zorg dat je telefoon de server kan bereiken. Het makkelijkst en veiligst is **Tailscale** (gratis):
   installeer het op de server én je telefoon en log op beide in met hetzelfde account. Je adres wordt dan
   `http://<naam-van-je-server>:8080/ask`. (Zet poort 8080 niet zomaar open op internet.)

**iPhone – app Opdrachten → + (nieuwe opdracht), noem hem "Assistent":**
1. *Dicteer tekst* (taal: Nederlands; stoppen met luisteren: "Na pauze").
2. *Haal inhoud van URL op*: URL `http://<server>:8080/ask`, methode **POST**,
   header `Authorization` = `Bearer <jouw API_TOKEN>`, hoofdtekst **JSON** met veld `text` =
   *Gedicteerde tekst*.
3. *Haal woordenboekwaarde op*: sleutel `reply` uit *Inhoud van URL*.
4. *Spreek tekst uit*: *Woordenboekwaarde*. (Of *Toon resultaat* als je liever leest.)

Zeg nu **"Hé Siri, Assistent"**. Tip: koppel de opdracht ook aan de **Actieknop** of aan
*Instellingen → Toegankelijkheid → Aanraken → Tik op achterkant*.
Voor **typen**: dupliceer de opdracht als "Typ assistent" en vervang stap 1 door *Vraag om invoer*
(en zet in stap 2 ook `spoken` = `false` als je opmaak wél wilt zien). Zet hem als widget op je beginscherm.

**Android – met Tasker** (taak "Assistent"):
1. *Input → Get Voice* (taal nl-NL).
2. *Net → HTTP Request*: POST naar `http://<server>:8080/ask`, header
   `Authorization:Bearer <jouw API_TOKEN>`, body `{"text":"%gv_heard"}`, content type `application/json`.
3. *Alert → Say*: `%http_data.reply`.

Zet de taak als snelkoppeling/widget op je beginscherm. Voor typen: vervang stap 1 door
*Variable Query*.

**Even testen vanaf een computer:**
```bash
curl -X POST http://<server>:8080/ask -H "Authorization: Bearer <API_TOKEN>" \
     -H "Content-Type: application/json" -d '{"text":"Wat staat er morgen in mijn agenda?"}'
```

## Commando's

- Gewoon typen: praten met je assistent
- `/taken`: je openstaande taken
- `/herinneringen`: geplande herinneringen
- `/reset`: nieuw gesprek (taken, herinneringen en geheugen blijven bewaard)

## Techniek

- `assistant/bot.py`: Telegram-interface, spraakberichten, herinneringslus (elke 20 s), bevestigknoppen
- `assistant/api.py`: HTTP-ingang `/ask` voor Siri/Tasker; `assistant/voice.py`: spraak → tekst
- `assistant/agent.py`: Claude-agentlus (model `claude-opus-5-5`, web search, server-side
  compaction voor lange gesprekken, automatische fallback bij een weigering)
- `assistant/tools.py`: alle tools; `assistant/db.py`: SQLite-opslag in `data/`
- `assistant/integrations/`: Google (Agenda/Gmail) en Microsoft Graph (Outlook)

Instellingen in `.env`: `TIMEZONE` (standaard `Europe/Amsterdam`), `CLAUDE_MODEL`, `CLAUDE_EFFORT`
(`low` = sneller en goedkoper, `high` = grondiger).

Tests: `pip install pytest && python -m pytest`
