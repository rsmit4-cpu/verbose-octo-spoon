"""Eenmalig: koppel Google Agenda + Gmail.

1. Maak in Google Cloud Console een OAuth-client van het type 'Desktop app'
   (APIs: Google Calendar API en Gmail API inschakelen).
2. Download het JSON-bestand en zet het in data/google_credentials.json.
3. Draai: python -m assistant.setup_google   (opent je browser)
"""
from google_auth_oauthlib.flow import InstalledAppFlow

from . import config
from .integrations.google import SCOPES


def main() -> None:
    cfg = config.load()
    if not cfg.google_credentials.exists():
        raise SystemExit(f"Zet eerst je OAuth-clientbestand in {cfg.google_credentials}")
    flow = InstalledAppFlow.from_client_secrets_file(str(cfg.google_credentials), SCOPES)
    creds = flow.run_local_server(port=0)
    cfg.google_token.write_text(creds.to_json())
    print(f"Gelukt! Token opgeslagen in {cfg.google_token}")


if __name__ == "__main__":
    main()
