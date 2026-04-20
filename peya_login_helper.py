"""
Script auxiliar para el login de PedidosYa.
1. Intenta login automático con email/password en /login
2. Si se requiere 2FA, imprime {"status": "2fa_required"} y espera flag manual
3. Extrae el token + device token
4. Calcula los totales de órdenes por grupo
5. Imprime JSON en stdout:
   {"token": "...", "totales": {...}, "device_token": "...", "reclamos_data": []}

Nota: los reclamos ya no se obtienen aquí; se descargan por webhook n8n en main.py.

Uso: python peya_login_helper.py <flag_file> <state_file> <desde> <hasta> [vendor_codes_json] [email] [password]
"""
import asyncio, sys, json
from pathlib import Path

FLAG         = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".peya_login_ok")
STATE_FILE   = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".peya_browser_state.json")
DESDE        = sys.argv[3] if len(sys.argv) > 3 else None
HASTA        = sys.argv[4] if len(sys.argv) > 4 else None
GRUPOS_CODES = json.loads(sys.argv[5]) if len(sys.argv) > 5 else {}
PEYA_EMAIL   = sys.argv[6] if len(sys.argv) > 6 else ""
PEYA_PASSWORD= sys.argv[7] if len(sys.argv) > 7 else ""

PERF_URL = "https://vos-api.us.prd.portal.restaurant/v1/vendors/reports/performance"


TOKEN_JS = """
    (() => {
        try {
            const root = localStorage.getItem('persist:root');
            if (!root) return null;
            const auth = JSON.parse(JSON.parse(root).authentication);
            return auth.accessToken || null;
        } catch(e) { return null; }
    })()
"""


async def _wait_for_token(page, timeout_ms=30_000) -> bool:
    """Espera hasta timeout_ms ms a que aparezca el token en localStorage. Devuelve True si lo encuentra."""
    try:
        await page.wait_for_function(TOKEN_JS, timeout=timeout_ms)
        return True
    except Exception:
        return False


async def main():
    from playwright.async_api import async_playwright
    FLAG.unlink(missing_ok=True)
    STATE_FILE.unlink(missing_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False, slow_mo=200,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])

        context = await browser.new_context(
            viewport={"width": 1280, "height": 800}, locale="es-AR",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

        page = await context.new_page()
        await page.goto("https://portal-app.pedidosya.com/login",
                        wait_until="networkidle")

        # ── Intento de login automático con credenciales ──────────────────────
        login_automatico = False
        if PEYA_EMAIL and PEYA_PASSWORD:
            try:
                # Esperar el campo de email (la página /login usa inputs estándar)
                EMAIL_SELECTORS = [
                    'input[type="email"]',
                    'input[name="email"]',
                    'input[name="username"]',
                ]
                email_sel = None
                for sel in EMAIL_SELECTORS:
                    try:
                        await page.wait_for_selector(sel, timeout=5_000)
                        email_sel = sel
                        break
                    except Exception:
                        continue

                if not email_sel:
                    raise RuntimeError("No se encontró el campo de email en el formulario")

                # Completar email y password
                await page.fill(email_sel, PEYA_EMAIL)
                await page.fill('input[type="password"]', PEYA_PASSWORD)

                # Enviar formulario
                submit = page.locator('button[type="submit"]').first
                await submit.click()

                # Esperar hasta 30s a que aparezca el token (login exitoso)
                login_automatico = await _wait_for_token(page, timeout_ms=30_000)

            except Exception:
                login_automatico = False

        # ── Si no hay token, asumir 2FA u otro desafío manual ────────────────
        if not login_automatico:
            print('{"status": "2fa_required"}', flush=True)
            while not FLAG.exists():
                await asyncio.sleep(0.5)
            FLAG.unlink(missing_ok=True)
            await asyncio.sleep(2)

        # ── Extraer token + device token ──────────────────────────────────────
        token_data = await page.evaluate("""
            (() => {
                try {
                    const root = localStorage.getItem('persist:root');
                    if (!root) return null;
                    const auth = JSON.parse(JSON.parse(root).authentication);
                    let deviceToken = auth.deviceToken || null;
                    if (!deviceToken) {
                        try {
                            deviceToken = JSON.parse(
                                JSON.parse(root).device || '{}'
                            ).deviceToken || null;
                        } catch(e2) {}
                    }
                    return { accessToken: auth.accessToken || null,
                             deviceToken: deviceToken };
                } catch(e) { return null; }
            })()
        """)

        token        = (token_data or {}).get("accessToken")
        device_token = (token_data or {}).get("deviceToken") or ""

        if not token:
            await browser.close()
            print(json.dumps({"token": None, "totales": {},
                               "device_token": "", "reclamos_data": []}), flush=True)
            return

        # Guardar estado del browser para usos posteriores
        state = await context.storage_state()
        STATE_FILE.write_text(json.dumps(state))

        # ── Totales de órdenes por grupo ──────────────────────────────────────
        totales = {}
        if GRUPOS_CODES and DESDE and HASTA:
            for grupo, vendor_codes in GRUPOS_CODES.items():
                body = json.dumps({
                    "global_vendor_codes": vendor_codes,
                    "from": DESDE, "to": HASTA, "precision": "DAY"
                })
                result = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const r = await fetch('{PERF_URL}', {{
                                method: 'POST',
                                headers: {{
                                    'Content-Type': 'application/json',
                                    'Authorization': (() => {{
                                        const root = localStorage.getItem('persist:root');
                                        const auth = JSON.parse(JSON.parse(root).authentication);
                                        return 'Bearer ' + auth.accessToken;
                                    }})()
                                }},
                                body: JSON.stringify({json.loads(body)})
                            }});
                            const data = await r.json();
                            return {{ status: r.status, data: data }};
                        }} catch(e) {{
                            return {{ status: 0, error: e.toString() }};
                        }}
                    }}
                """)
                if result and result.get("status") == 200:
                    data = result.get("data", {}).get("data", [])
                    totales[grupo] = sum(int(i.get("orderCount", 0))
                                        for i in data) if isinstance(data, list) else 0
                else:
                    totales[grupo] = 0

        await browser.close()
        print(json.dumps({
            "token":         token,
            "totales":       totales,
            "device_token":  device_token,
            "reclamos_data": [],
        }), flush=True)


asyncio.run(main())
