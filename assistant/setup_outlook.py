"""Eenmalig: koppel je Outlook-agenda (Microsoft Graph).

1. Registreer een app op https://entra.microsoft.com -> App-registraties -> Nieuwe registratie
   (accounttype: 'persoonlijke Microsoft-accounts' of je organisatie), en zet onder
   'Verificatie' -> 'Openbare clientstromen toestaan' op Ja.
2. Zet de Application (client) ID in .env als MS_CLIENT_ID (en MS_TENANT=consumers voor
   outlook.com/hotmail, of 'organizations' voor een werkaccount).
3. Draai: python -m assistant.setup_outlook   en volg de instructies (code invoeren op je telefoon kan ook).
"""
from . import config
from .integrations.outlook import SCOPES, _app


def main() -> None:
    cfg = config.load()
    if not cfg.ms_client_id:
        raise SystemExit("MS_CLIENT_ID ontbreekt in .env")
    app, cache = _app(cfg.ms_client_id, cfg.ms_tenant, cfg.ms_token_cache)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise SystemExit(f"Kon apparaatlogin niet starten: {flow}")
    print(flow["message"])
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise SystemExit(f"Inloggen mislukt: {result.get('error_description')}")
    cfg.ms_token_cache.write_text(cache.serialize())
    print(f"Gelukt! Outlook gekoppeld; token opgeslagen in {cfg.ms_token_cache}")


if __name__ == "__main__":
    main()
