"""
Timeouts parametrizables por variables de entorno.

Pensado para corridas de periodos largos (mensuales) donde las APIs tardan
mas en responder. Cada valor se puede sobrescribir desde `.env`:

    HTTP_TIMEOUT=300            # requests.post / requests.get a APIs de Rappi/PeYa
    WEBHOOK_TIMEOUT=600         # descarga de CSV via webhook n8n / Apps Script
    PLAYWRIGHT_LOGIN_TIMEOUT_MS=60000     # esperar selector de login
    PLAYWRIGHT_TOKEN_TIMEOUT_MS=120000    # esperar token en localStorage
    PLAYWRIGHT_CAPTCHA_TIMEOUT_MS=600000  # esperar resolucion manual de captcha
    SHEETS_TIMEOUT=30           # urlopen contra Google Sheets

Si la variable no esta definida o es invalida, se usa el default razonable.
"""
import os


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (ValueError, AttributeError):
        return default


HTTP_TIMEOUT                  = _int("HTTP_TIMEOUT",                  300)
WEBHOOK_TIMEOUT               = _int("WEBHOOK_TIMEOUT",               600)
SHEETS_TIMEOUT                = _int("SHEETS_TIMEOUT",                 30)
PLAYWRIGHT_LOGIN_TIMEOUT_MS   = _int("PLAYWRIGHT_LOGIN_TIMEOUT_MS",  60_000)
PLAYWRIGHT_TOKEN_TIMEOUT_MS   = _int("PLAYWRIGHT_TOKEN_TIMEOUT_MS", 120_000)
PLAYWRIGHT_CAPTCHA_TIMEOUT_MS = _int("PLAYWRIGHT_CAPTCHA_TIMEOUT_MS", 600_000)
