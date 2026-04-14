"""
Script auxiliar para el login de PedidosYa.
1. Abre el browser y espera el login manual
2. Extrae el token + device token
3. Calcula los totales de órdenes por grupo
4. Obtiene reclamos (ListOrders + GetOrderDetails) desde el mismo browser
5. Imprime JSON en stdout:
   {"token": "...", "totales": {...}, "device_token": "...", "reclamos_data": [...]}

Uso: python peya_login_helper.py <flag_file> <state_file> <desde> <hasta> [vendor_codes_json]
"""
import asyncio, sys, json
from pathlib import Path

FLAG         = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".peya_login_ok")
STATE_FILE   = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".peya_browser_state.json")
DESDE        = sys.argv[3] if len(sys.argv) > 3 else None
HASTA        = sys.argv[4] if len(sys.argv) > 4 else None
GRUPOS_CODES = json.loads(sys.argv[5]) if len(sys.argv) > 5 else {}

PERF_URL = "https://vos-api.us.prd.portal.restaurant/v1/vendors/reports/performance"
GQL_URL  = "https://vagw-api.us.prd.portal.restaurant/query"

GQL_LIST_ORDERS = (
    "query ListOrders($params: ListOrdersReq!) { "
    "orders { listOrders(input: $params) { "
    "nextPageToken orders { "
    "orderId globalEntityId vendorId vendorName "
    "orderStatus placedTimestamp orderIssues "
    "} } } }"
)

GQL_ORDER_DETAIL = (
    "query GetOrderDetails($params: OrderReq!) { "
    "orders { order(input: $params) { "
    "order { orderId vendorId vendorName "
    "items { id: productId name } } "
    "orderIssues { orderIssue metadata { reason } } "
    "} } }"
)


async def _get_auth_info(page) -> dict:
    """Extrae token, device token y user/vendor IDs desde localStorage del browser."""
    return await page.evaluate("""
        (() => {
            try {
                const root = localStorage.getItem('persist:root');
                const auth = JSON.parse(JSON.parse(root).authentication);
                const tok  = auth.accessToken || '';
                let payload = {};
                try { payload = JSON.parse(atob(tok.split('.')[1])); } catch(e2) {}
                return {
                    token:  tok,
                    device: auth.deviceToken || '',
                    userId: payload.sub || '',
                    lpvid:  (payload.metadata && payload.metadata.lpvid) || ''
                };
            } catch(e) { return {token:'', device:'', userId:'', lpvid:''}; }
        })()
    """) or {}


async def _gql(page, body_dict: dict, auth: dict | None = None) -> dict:
    """
    Ejecuta una llamada GraphQL usando page.request.post() de Playwright.
    Esto bypasea las restricciones CORS de JavaScript fetch y accede a las
    cookies del contexto del browser automáticamente.
    """
    if auth is None:
        auth = await _get_auth_info(page)

    headers = {
        "Content-Type":              "application/json",
        "accept":                    "*/*",
        "accept-language":           "en-US,en;q=0.9,es;q=0.8",
        "apollographql-client-name": "API Gateway",
        "x-app-name":                "one-web",
        "x-country":                 "AR",
        "x-global-entity-id":        "PY_AR",
        "Authorization":             f"Bearer {auth.get('token', '')}",
    }
    if auth.get("device"):
        headers["x-rps-device"] = auth["device"]
    if auth.get("userId"):
        headers["x-user-id"] = auth["userId"]
    if auth.get("lpvid"):
        headers["x-vendor-id"] = auth["lpvid"]

    try:
        resp = await page.request.post(
            GQL_URL,
            data=json.dumps(body_dict),
            headers=headers,
        )
        if not resp.ok:
            return {"status": resp.status, "data": {}}
        return {"status": resp.status, "data": await resp.json()}
    except Exception as e:
        return {"status": 0, "error": str(e), "data": {}}


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
        await page.goto("https://portal-app.pedidosya.com/phone-login",
                        wait_until="networkidle")

        # Esperar flag file (el usuario completa el login)
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

        # ── Reclamos: ListOrders + GetOrderDetails desde este mismo browser ───
        reclamos_data = []
        if DESDE and HASTA and GRUPOS_CODES:
            auth_info = await _get_auth_info(page)
            # Construir lista de vendors desde GRUPOS_CODES
            all_vendor_codes = [
                {"globalEntityId": "PY_AR", "vendorId": code.split(";")[-1]}
                for codes in GRUPOS_CODES.values()
                for code in codes
                if ";" in code and code.split(";")[-1].isdigit()
            ]

            # ── Paso 1: listar órdenes reclamadas (paginado) ──────────────
            all_orders = []
            page_token = None
            while True:
                pagination = {"pageSize": 1000}
                if page_token:
                    pagination["pageToken"] = page_token

                list_result = await _gql(page, auth=auth_info, body_dict={
                    "operationName": "ListOrders",
                    "variables": {
                        "params": {
                            "pagination": pagination,
                            "filter": {"transactionStatuses": ["REFUNDED", "CHARGED"]},
                            "timeFrom": f"{DESDE}T03:00:00.000Z",
                            "timeTo":   f"{HASTA}T03:00:00.000Z",
                            "globalVendorCodes": all_vendor_codes,
                        }
                    },
                    "query": GQL_LIST_ORDERS,
                })

                if list_result.get("status") != 200:
                    break

                _r1         = (list_result.get("data") or {})
                _r2         = (_r1.get("data") or {})
                _r3         = (_r2.get("orders") or {})
                list_orders = (_r3.get("listOrders") or {})
                orders      = list_orders.get("orders") or []
                next_token  = list_orders.get("nextPageToken")
                all_orders.extend(orders)

                if not next_token or len(orders) < 1000:
                    break
                page_token = next_token

            # ── Paso 2: detalle por orden ─────────────────────────────────
            for orden in all_orders:
                oid = str(orden.get("orderId", "")).strip()
                vid = str(orden.get("vendorId", "")).strip()
                ts  = str(orden.get("placedTimestamp", ""))
                if not oid:
                    continue

                det_result = await _gql(page, auth=auth_info, body_dict={
                    "operationName": "GetOrderDetails",
                    "variables": {
                        "params": {
                            "orderId":                  oid,
                            "GlobalVendorCode":         {"globalEntityId": "PY_AR",
                                                          "vendorId": vid},
                            "placedTimestamp":          ts,
                            "isBillingDataFlagEnabled": False,
                        },
                        "orderIssueParams": {
                            "orderId":          oid,
                            "GlobalVendorCode": {"globalEntityId": "PY_AR",
                                                  "vendorId": vid},
                        },
                        "hasPhotoEvidence": False,
                    },
                    "query": GQL_ORDER_DETAIL,
                })

                detalle = {}
                if det_result.get("status") == 200:
                    _d1     = (det_result.get("data") or {})
                    _d2     = (_d1.get("data") or {})
                    _d3     = (_d2.get("orders") or {})
                    detalle = (_d3.get("order") or {})

                reclamos_data.append({"orden": orden, "detalle": detalle})
                await asyncio.sleep(0.25)

        await browser.close()
        print(json.dumps({
            "token":         token,
            "totales":       totales,
            "device_token":  device_token,
            "reclamos_data": reclamos_data,
        }), flush=True)


asyncio.run(main())
