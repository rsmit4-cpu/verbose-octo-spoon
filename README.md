# Persoonlijke assistent (WhatsApp + Claude)

Een persoonlijke assistent die je via **WhatsApp** gebruikt: je slaat hem op als contact "Assistent" en
appt of spreekt hem in zoals ieder ander. Claude is het brein; hij kan meedenken, dingen opzoeken, taken bijhouden, herinneringen als pushbericht sturen en je
Google Agenda, Gmail en Outlook-agenda gebruiken.

## Wat kan hij?

| Functie | Voorbeeld |
|---|---|
| Meedenken & web zoeken | "Help me een weekendje Gent plannen" · "Wat is het weer zaterdag?" |
| Herinneringen (push) | "Herinner me morgen om 9:00 aan de tandarts" · "Elke maandag 8:00 aan de kliko" |
| Sportwedstrijden | "Wanneer speelt Ajax? Herinner me een kwartier van tevoren" (zoekt de aftrap op) |
| Taken / to-do's | "Zet 'verzekering opzeggen' op mijn lijst" · `taken` |
| Geheugen | "Onthoud dat ik een iPhone heb en fan ben van PSV" |
| Google Agenda | "Wat staat er deze week in mijn agenda?" · "Zet vrijdag 14:00 een afspraak met Sanne" |
| Outlook-agenda | Zelfde als hierboven, in je Outlook-/werkagenda |
| Gmail | "Heb ik belangrijke ongelezen mail?" · "Schrijf een antwoord aan Jan" (versturen pas na jouw tik op ✅) |
| Spraakberichten | Houd de 🎤 ingedrukt in WhatsApp en spreek je vraag in |

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
een **Anthropic API-sleutel** (<https://console.anthropic.com>) en een (gratis) **Meta-ontwikkelaarsaccount**.

```bash
git clone <deze repo> && cd verbose-octo-spoon
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # en vul de waarden in
```

### Stap 1 – De server bereikbaar maken (HTTPS)
WhatsApp levert berichten af op een openbaar **https**-adres. Het makkelijkst gratis is **Tailscale Funnel**:
installeer [Tailscale](https://tailscale.com) op de server, log in en zet Funnel aan in de beheeromgeving. Dan:

```bash
tailscale funnel --bg 8080
```

Je krijgt een adres als `https://mijnpc.tail1234.ts.net`. (Alternatief: Cloudflare Tunnel.)
Alleen berichten met een geldige Meta-handtekening en alleen jouw nummer worden verwerkt.

### Stap 2 – Een WhatsApp-nummer voor je assistent (Meta)
De assistent heeft een **eigen nummer** nodig; je persoonlijke WhatsApp blijft gewoon werken.
(Er bestaan ook onofficiële koppelingen die je eigen WhatsApp "overnemen", maar die zijn in strijd met de
voorwaarden van WhatsApp en kunnen je nummer laten blokkeren. Deze assistent gebruikt daarom de officiële API.)

1. Ga naar <https://developers.facebook.com> → *Mijn apps* → *App maken* → kies het gebruik
   *Contact maken met klanten via WhatsApp* (type *Business*).
2. Ga naar *WhatsApp → API-instellingen* (API Setup). Meta geeft je gratis een **testnummer**.
   - Voeg bij *Aan* je **eigen mobiele nummer** toe en bevestig met de code.
     (Met het testnummer kun je naar maximaal 5 eigen nummers appen: perfect voor persoonlijk gebruik.)
   - Kopieer de **Phone number ID** naar `WHATSAPP_PHONE_NUMBER_ID`.
3. **Blijvend toegangstoken** (het token op die pagina verloopt na 24 uur):
   *Bedrijfsinstellingen* (business.facebook.com/settings) → *Systeemgebruikers* → *Toevoegen* (rol Admin) →
   *Assets toewijzen*: je app → *Token genereren* met de rechten `whatsapp_business_messaging` en
   `whatsapp_business_management`. Zet het in `WHATSAPP_TOKEN`.
4. *App-instellingen → Basis* → **App-geheim** → `WHATSAPP_APP_SECRET`.
5. Verzin een wachtwoord voor `WHATSAPP_VERIFY_TOKEN` en zet je eigen nummer in `ALLOWED_NUMBERS`
   (bijv. `+31612345678`).
6. Start de assistent: `python -m assistant`
7. *WhatsApp → Configuratie* → *Webhook bewerken*: Callback-URL `https://<jouw-adres>/webhook`,
   verificatietoken = je `WHATSAPP_VERIFY_TOKEN` → *Verifiëren en opslaan*. Klik daarna bij
   *Webhookvelden* op *Abonneren* bij **messages**.
8. Sla het testnummer op in je telefoon als **"Assistent"** en stuur hem `hulp`. Klaar!

### Stap 3 (aanbevolen) – Herinneringen na 24 uur stilte
WhatsApp-regel: een bedrijfsnummer mag je alleen vrij berichten sturen binnen **24 uur na jouw laatste
bericht**. Voor een herinnering daarna (bijv. een wedstrijd volgende week, terwijl je tussendoor niet hebt
geappt) is een goedgekeurd **sjabloon** nodig:

1. *WhatsApp Manager → Berichtsjablonen → Sjabloon maken*: categorie **Hulpprogramma** (Utility),
   naam `herinnering`, taal **Nederlands**, tekst: `⏰ Herinnering: {{1}}`. Goedkeuring duurt meestal minuten.
2. Zet in `.env`: `WHATSAPP_REMINDER_TEMPLATE=herinnering`.

De assistent probeert eerst een gewoon bericht en gebruikt het sjabloon alleen als dat nodig is.
Gewone gesprekken zijn gratis; sjabloonberichten kosten Meta-tarief (enkele centen per bericht).
Zonder sjabloon komen zulke "late" herinneringen niet aan. Tip: wie dagelijks even appt, merkt hier niets van.

### Google Agenda + Gmail koppelen (optioneel)

1. Ga naar <https://console.cloud.google.com>, maak een project en schakel de **Google Calendar API** en
   **Gmail API** in.
2. *APIs en services → OAuth-toestemmingsscherm*: type *Extern*, voeg jezelf toe als testgebruiker.
3. *Inloggegevens → OAuth-client-ID → Desktop-app*, download het JSON-bestand naar
   `data/google_credentials.json`.
4. `python -m assistant.setup_google` (opent je browser) en herstart de assistent.

### Outlook-agenda koppelen (optioneel)

1. Ga naar <https://entra.microsoft.com> → *App-registraties → Nieuwe registratie*. Kies
   persoonlijke Microsoft-accounts (outlook.com/hotmail) en/of je organisatie.
2. Onder *Verificatie*: *Openbare clientstromen toestaan* → **Ja**.
3. Zet de *Application (client) ID* in `.env` als `MS_CLIENT_ID`
   (`MS_TENANT=consumers` voor privé, `organizations` voor werk).
4. `python -m assistant.setup_outlook` en volg de instructies; herstart de assistent.

## Snel aanroepen: met je stem of door te typen

### 1. In WhatsApp (werkt direct)
- **Typen:** gewoon een bericht sturen naar "Assistent".
- **Spreken:** houd de 🎤-knop ingedrukt en spreek een spraakbericht in. De assistent zet het lokaal en gratis
  om naar tekst (faster-whisper; de eerste keer wordt het spraakmodel eenmalig gedownload, ~500 MB) en laat
  zien wat hij verstond.
- **Met Siri / Google Assistent:** "Hé Siri, stuur een WhatsApp naar Assistent: herinner me morgen om negen
  uur aan de tandarts". Dat werkt ingebouwd, zonder iets in te stellen.
- **Sneller openen:** zet de chat vast bovenaan in WhatsApp. Op Android: chat → ⋮ → *Meer* →
  *Snelkoppeling toevoegen*.

### 2. "Hé Siri, Assistent" met voorgelezen antwoord
Hiermee spreek je in of typ je, en het antwoord wordt **voorgelezen**, zonder WhatsApp te openen.
Het is hetzelfde gesprek als in WhatsApp.

**Eenmalig op de server:**
1. Maak een geheime sleutel: `python -c "import secrets; print(secrets.token_urlsafe(32))"` en zet die
   in `.env` als `API_TOKEN`. Herstart de assistent.
2. Je gebruikt hetzelfde https-adres als bij stap 1 van de installatie: `https://<jouw-adres>/ask`.
   Zonder geldige sleutel weigert de server elk verzoek.

**iPhone – app Opdrachten → + (nieuwe opdracht), noem hem "Assistent":**
1. *Dicteer tekst* (taal: Nederlands; stoppen met luisteren: "Na pauze").
2. *Haal inhoud van URL op*: URL `https://<jouw-adres>/ask`, methode **POST**,
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
2. *Net → HTTP Request*: POST naar `https://<jouw-adres>/ask`, header
   `Authorization:Bearer <jouw API_TOKEN>`, body `{"text":"%gv_heard"}`, content type `application/json`.
3. *Alert → Say*: `%http_data.reply`.

Zet de taak als snelkoppeling/widget op je beginscherm. Voor typen: vervang stap 1 door
*Variable Query*.

**Even testen vanaf een computer:**
```bash
curl -X POST https://<jouw-adres>/ask -H "Authorization: Bearer <API_TOKEN>" \
     -H "Content-Type: application/json" -d '{"text":"Wat staat er morgen in mijn agenda?"}'
```

## Commando's

- Gewoon typen of inspreken: praten met je assistent
- `hulp`: uitleg en voorbeelden
- `taken`: je openstaande taken
- `herinneringen`: geplande herinneringen
- `reset`: nieuw gesprek (taken, herinneringen en geheugen blijven bewaard)

## Techniek

- `assistant/server.py`: WhatsApp-webhook, spraakberichten, herinneringslus (elke 20 s), bevestigknoppen
- `assistant/whatsapp.py`: WhatsApp Business Cloud API (versturen, media, handtekeningcontrole)
- `assistant/api.py`: HTTP-ingang `/ask` voor Siri/Tasker; `assistant/voice.py`: spraak → tekst
- `assistant/agent.py`: Claude-agentlus (model `claude-opus-5-5`, web search, server-side
  compaction voor lange gesprekken, automatische fallback bij een weigering)
- `assistant/tools.py`: alle tools; `assistant/db.py`: SQLite-opslag in `data/`
- `assistant/integrations/`: Google (Agenda/Gmail) en Microsoft Graph (Outlook)

Instellingen in `.env`: `TIMEZONE` (standaard `Europe/Amsterdam`), `CLAUDE_MODEL`, `CLAUDE_EFFORT`
(`low` = sneller en goedkoper, `high` = grondiger).

Tests: `pip install pytest && python -m pytest`
