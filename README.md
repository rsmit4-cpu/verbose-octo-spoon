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

## Commando's

- Gewoon typen: praten met je assistent
- `/taken`: je openstaande taken
- `/herinneringen`: geplande herinneringen
- `/reset`: nieuw gesprek (taken, herinneringen en geheugen blijven bewaard)

## Techniek

- `assistant/bot.py`: Telegram-interface, herinneringslus (elke 20 s), bevestigknoppen
- `assistant/agent.py`: Claude-agentlus (model `claude-opus-5-5`, web search, server-side
  compaction voor lange gesprekken, automatische fallback bij een weigering)
- `assistant/tools.py`: alle tools; `assistant/db.py`: SQLite-opslag in `data/`
- `assistant/integrations/`: Google (Agenda/Gmail) en Microsoft Graph (Outlook)

Instellingen in `.env`: `TIMEZONE` (standaard `Europe/Amsterdam`), `CLAUDE_MODEL`, `CLAUDE_EFFORT`
(`low` = sneller en goedkoper, `high` = grondiger).

Tests: `pip install pytest && python -m pytest`
