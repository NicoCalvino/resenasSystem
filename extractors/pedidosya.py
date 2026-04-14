"""
Extractor PedidosYa — flujo real (replicado del VBA del Excel):

Login:
  1. Playwright abre portal-app.pedidosya.com/phone-login
  2. Pausa — el usuario completa el login manualmente (SMS o usuario/pass)
  3. Extrae token de localStorage: JSON.parse(localStorage.getItem('persist:root'))
     → accessToken + deviceToken → Bearer token

APIs:
  - Reseñas:  POST vrs-api.us.prd.portal.restaurant/v1/reviews
  - Totales:  POST vos-api.us.prd.portal.restaurant/v1/vendors/reports/performance
"""
import asyncio, base64, logging, os, sys, time, uuid
from pathlib import Path
import requests, json
from datetime import datetime, timedelta
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from config.models import Resena, Reclamo
from config.locales import PY_INDEX, ALL_PY_IDS, TIENDAS

logger = logging.getLogger(__name__)

LOGIN_URL   = "https://portal-app.pedidosya.com/phone-login"
REVIEWS_URL = "https://vrs-api.us.prd.portal.restaurant/v1/reviews"
PERF_URL    = "https://vos-api.us.prd.portal.restaurant/v1/vendors/reports/performance"
PEYA_GQL_URL = "https://vagw-api.us.prd.portal.restaurant/query"


# ── Helpers ───────────────────────────────────────────────────────────────────
def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def _jwt_sub(token: str) -> str:
    """Extrae el campo 'sub' (user ID) del payload JWT sin librerías externas."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data.get("sub", "")
    except Exception:
        return ""


def _h_gql(token: str) -> dict:
    """
    Headers para el endpoint GraphQL del portal PedidosYa.
    Replica exactamente los headers que envía el browser (extraídos del network tab).
    """
    rps_device = os.environ.get("PEYA_DEVICE_TOKEN", "")
    user_id    = os.environ.get("PEYA_USER_ID", "") or _jwt_sub(token)

    h = {
        "Authorization":              f"Bearer {token}",
        "Content-Type":               "application/json",
        "accept":                     "*/*",
        "apollographql-client-name":  "API Gateway",
        "x-app-name":                 "one-web",
        "x-country":                  "AR",
        "x-global-entity-id":         "PY_AR",
        "x-request-id":               str(uuid.uuid4()),
        "Origin":                     "https://portal-app.pedidosya.com",
        "Referer":                    "https://portal-app.pedidosya.com/",
        "User-Agent":                 "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                                      "Chrome/146.0.0.0 Safari/537.36",
    }
    if rps_device:
        h["x-rps-device"] = rps_device
    if user_id:
        h["x-user-id"] = user_id
    return h

def _diso(dt: datetime) -> str:
    """Formato ISO que usa PedidosYa: 2026-03-31T03:00:00.000Z"""
    return dt.strftime("%Y-%m-%dT03:00:00.000Z")


# ── Traducción de tipos de issue PedidosYa ────────────────────────────────────
PEYA_ISSUE_TRADUCCION = {
    "ITEM_MISSING":        "FALTÓ UN ITEM",
    "WRONG_ITEM":          "ITEM INCORRECTO",
    "EXTRA_ITEM":          "ITEM DE MÁS",
    "MISSING_ORDER":       "PEDIDO NO ENTREGADO",
    "WRONG_ORDER":         "PEDIDO INCORRECTO",
    "PARTIAL_REFUND":      "REEMBOLSO PARCIAL",
    "FULL_REFUND":         "REEMBOLSO TOTAL",
    "QUALITY":             "PROBLEMAS DE CALIDAD",
    "LATE_DELIVERY":       "ENTREGA TARDÍA",
    "MISSING_ITEMS":       "FALTARON ITEMS",
    "RESTAURANT_ISSUE":    "PROBLEMA DEL LOCAL",
    "OTHER":               "OTRO",
}

# ── GraphQL queries (strings) ─────────────────────────────────────────────────
_GQL_LIST_ORDERS = (
    "query ListOrders($params: ListOrdersReq!) { "
    "orders { listOrders(input: $params) { "
    "nextPageToken orders { "
    "orderId globalEntityId vendorId vendorName "
    "orderStatus placedTimestamp orderIssues "
    "} } } }"
)

_GQL_ORDER_DETAIL = (
    "query GetOrderDetails($params: OrderReq!) { "
    "orders { order(input: $params) { "
    "order { orderId vendorId vendorName "
    "items { id: productId name } } "
    "orderIssues { orderIssue metadata { reason } } "
    "} } }"
)


# ── API RECLAMOS — paso 1: listar órdenes REFUNDED/CHARGED ───────────────────
async def _peya_auth_desde_browser(page) -> dict:
    """Extrae token, device token y IDs desde localStorage del browser."""
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


async def _peya_gql_request(page, body: dict, auth: dict) -> dict:
    """
    Hace una llamada GraphQL usando page.request.post() de Playwright.
    Bypasea las restricciones CORS del JS fetch y accede a las cookies del
    contexto del browser automáticamente.
    """
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
    if auth.get("device"):  headers["x-rps-device"] = auth["device"]
    if auth.get("userId"):  headers["x-user-id"]    = auth["userId"]
    if auth.get("lpvid"):   headers["x-vendor-id"]  = auth["lpvid"]

    try:
        resp = await page.request.post(
            PEYA_GQL_URL, data=json.dumps(body), headers=headers)
        if not resp.ok:
            logger.warning(f"PedidosYa GQL (browser): status={resp.status}")
            return {}
        return await resp.json()
    except Exception as e:
        logger.warning(f"PedidosYa GQL (browser) error: {e}")
        return {}


async def _api_reclamos_detalle_desde_browser(page, order_id: str,
                                              vendor_id: str,
                                              placed_timestamp: str,
                                              auth: dict | None = None) -> dict:
    """GetOrderDetails vía page.request (sin restricciones CORS de JS fetch)."""
    if auth is None:
        auth = await _peya_auth_desde_browser(page)

    body = {
        "operationName": "GetOrderDetails",
        "variables": {
            "params": {
                "orderId":                  order_id,
                "GlobalVendorCode":         {"globalEntityId": "PY_AR",
                                             "vendorId": vendor_id},
                "placedTimestamp":          placed_timestamp,
                "isBillingDataFlagEnabled": False,
            },
            "orderIssueParams": {
                "orderId":          order_id,
                "GlobalVendorCode": {"globalEntityId": "PY_AR",
                                     "vendorId": vendor_id},
            },
            "hasPhotoEvidence": False,
        },
        "query": _GQL_ORDER_DETAIL,
    }
    result = await _peya_gql_request(page, body, auth)
    _o = ((result.get("data") or {}).get("orders") or {})
    return (_o.get("order") or {})


async def _fetch_reclamos_via_browser(desde: datetime, hasta: datetime) -> list[Reclamo]:
    """
    Obtiene y convierte reclamos PedidosYa completamente desde el browser.
    Usa PEYA_STATE_FILE para restaurar la sesión sin login manual.
    Fallback cuando las llamadas directas con requests dan 403.
    """
    state_file = os.environ.get("PEYA_STATE_FILE", "")
    if not state_file or not Path(state_file).exists():
        logger.warning("PedidosYa reclamos (browser fallback): sin estado guardado")
        return []

    ctx_kwargs = dict(
        viewport    = {"width": 1280, "height": 800},
        locale      = "es-AR",
        storage_state = state_file,
        user_agent  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    )
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True, slow_mo=200,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            page = await (await browser.new_context(**ctx_kwargs)).new_page()
            await page.goto("https://portal-app.pedidosya.com",
                            wait_until="domcontentloaded")
            logger.info("PedidosYa reclamos (browser fallback): browser listo")

            # Token actual desde el browser (para detalle vía requests)
            access_token = await page.evaluate("""
                (() => {
                    try {
                        const root = localStorage.getItem('persist:root');
                        const auth = JSON.parse(JSON.parse(root).authentication);
                        return auth.accessToken || '';
                    } catch(e) { return ''; }
                })()
            """)

            # Lista de órdenes reclamadas desde el browser
            raw_lista = await _api_reclamos_lista_desde_browser(
                page, access_token, ALL_PY_IDS, desde, hasta)

            # Detalle por orden — primero requests (headers corregidos),
            # fallback al browser si sigue dando error
            detalles: dict[str, dict] = {}
            for orden in raw_lista:
                oid = str(orden.get("orderId", "")).strip()
                vid = str(orden.get("vendorId", "")).strip()
                ts  = str(orden.get("placedTimestamp", ""))
                if not oid:
                    continue
                det = {}
                if access_token:
                    det = api_reclamos_detalle_peya(access_token, oid, vid, ts)
                if not det:
                    det = await _api_reclamos_detalle_desde_browser(page, oid, vid, ts)
                detalles[oid] = det

            await browser.close()

        return convertir_reclamos_peya(raw_lista, detalles)

    except Exception as e:
        logger.error(f"PedidosYa reclamos browser fallback error: {e}")
        return []


async def _api_reclamos_lista_desde_browser(page, token: str, py_ids: list,
                                             desde: datetime, hasta: datetime) -> list[dict]:
    """
    Versión de api_reclamos_lista_peya que corre dentro del browser Playwright.
    Usar como fallback si la llamada directa con requests da 403.
    """
    import json as _json

    global_vendor_codes = [
        {"globalEntityId": "PY_AR", "vendorId": str(vid)}
        for vid in py_ids
    ]
    all_orders: list[dict] = []
    page_token = None

    while True:
        pagination = {"pageSize": 1000}
        if page_token:
            pagination["pageToken"] = page_token

        body = {
            "operationName": "ListOrders",
            "variables": {
                "params": {
                    "pagination": pagination,
                    "filter": {"transactionStatuses": ["REFUNDED", "CHARGED"]},
                    "timeFrom": _diso(desde),
                    "timeTo":   _diso(hasta),
                    "globalVendorCodes": global_vendor_codes,
                }
            },
            "query": _GQL_LIST_ORDERS,
        }

        body_json = _json.dumps(body)
        result = await page.evaluate(f"""
            async () => {{
                try {{
                    const r = await fetch('{PEYA_GQL_URL}', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type':              'application/json',
                            'accept':                    '*/*',
                            'accept-language':           'en-US,en;q=0.9,es;q=0.8',
                            'apollographql-client-name': 'API Gateway',
                            'x-app-name':                'one-web',
                            'x-country':                 'AR',
                            'x-global-entity-id':        'PY_AR',
                            'Authorization': (() => {{
                                try {{
                                    const root = localStorage.getItem('persist:root');
                                    const auth = JSON.parse(JSON.parse(root).authentication);
                                    return 'Bearer ' + auth.accessToken;
                                }} catch(e) {{ return ''; }}
                            }})(),
                            'x-rps-device': (() => {{
                                try {{
                                    const root = localStorage.getItem('persist:root');
                                    const auth = JSON.parse(JSON.parse(root).authentication);
                                    return auth.deviceToken || '';
                                }} catch(e) {{ return ''; }}
                            }})(),
                            'x-user-id': (() => {{
                                try {{
                                    const root = localStorage.getItem('persist:root');
                                    const auth = JSON.parse(JSON.parse(root).authentication);
                                    const tok = auth.accessToken || '';
                                    const payload = JSON.parse(atob(tok.split('.')[1]));
                                    return payload.sub || '';
                                }} catch(e) {{ return ''; }}
                            }})(),
                            'x-vendor-id': (() => {{
                                try {{
                                    const root = localStorage.getItem('persist:root');
                                    const auth = JSON.parse(JSON.parse(root).authentication);
                                    const tok = auth.accessToken || '';
                                    const payload = JSON.parse(atob(tok.split('.')[1]));
                                    return (payload.metadata && payload.metadata.lpvid) || '';
                                }} catch(e) {{ return ''; }}
                            }})()
                        }},
                        body: {body_json!r}
                    }});
                    const data = await r.json();
                    return {{ status: r.status, data: data }};
                }} catch(e) {{
                    return {{ status: 0, error: e.toString() }};
                }}
            }}
        """)

        if not result or result.get("status") != 200:
            logger.warning(f"PedidosYa reclamos (browser): status={result.get('status')} "
                           f"error={result.get('error', '')}")
            break

        _rd         = (result.get("data") or {})
        _gql        = (_rd.get("data") or {})
        _ord        = (_gql.get("orders") or {})
        list_orders = (_ord.get("listOrders") or {})
        orders      = list_orders.get("orders") or []
        next_token  = list_orders.get("nextPageToken")

        logger.info(f"PedidosYa reclamos lista (browser) pág: {len(orders)} órdenes")
        all_orders.extend(orders)

        if not next_token or len(orders) < 1000:
            break
        page_token = next_token

    logger.info(f"PedidosYa reclamos (browser): {len(all_orders)} órdenes reclamadas")
    return all_orders


def api_reclamos_lista_peya(token: str, py_ids: list,
                             desde: datetime, hasta: datetime) -> list[dict]:
    """
    Consulta ListOrders filtrando por transactionStatuses REFUNDED y CHARGED.
    Pagina automáticamente usando nextPageToken.
    """
    global_vendor_codes = [
        {"globalEntityId": "PY_AR", "vendorId": str(vid)}
        for vid in py_ids
    ]
    all_orders: list[dict] = []
    page_token = None

    while True:
        pagination: dict = {"pageSize": 1000}
        if page_token:
            pagination["pageToken"] = page_token

        body = {
            "operationName": "ListOrders",
            "variables": {
                "params": {
                    "pagination": pagination,
                    "filter": {"transactionStatuses": ["REFUNDED", "CHARGED"]},
                    "timeFrom": _diso(desde),
                    "timeTo":   _diso(hasta),
                    "globalVendorCodes": global_vendor_codes,
                }
            },
            "query": _GQL_LIST_ORDERS,
        }

        try:
            r = requests.post(PEYA_GQL_URL, headers=_h_gql(token),
                              json=body, timeout=60)
            r.raise_for_status()
            result = r.json()
        except Exception as e:
            logger.error(f"PedidosYa reclamos lista: {e}")
            break

        list_orders = (result.get("data") or {}).get("orders", {}).get("listOrders", {})
        orders      = list_orders.get("orders", [])
        next_token  = list_orders.get("nextPageToken")

        logger.info(f"PedidosYa reclamos lista pág: {len(orders)} órdenes")
        all_orders.extend(orders)

        if not next_token or len(orders) < 1000:
            break
        page_token = next_token

    logger.info(f"PedidosYa reclamos: {len(all_orders)} órdenes reclamadas en total")
    return all_orders


# ── API RECLAMOS — paso 2: detalle por orden (inestable, con reintento) ───────
def api_reclamos_detalle_peya(token: str, order_id: str,
                               vendor_id: str,
                               placed_timestamp: str) -> dict:
    """
    GetOrderDetails para una orden. Reintenta hasta 2 veces ante error.
    Retorna {} si falla definitivamente.
    """
    body = {
        "operationName": "GetOrderDetails",
        "variables": {
            "params": {
                "orderId":                 order_id,
                "GlobalVendorCode":        {"globalEntityId": "PY_AR",
                                            "vendorId": vendor_id},
                "placedTimestamp":         placed_timestamp,
                "isBillingDataFlagEnabled": False,
            },
            "orderIssueParams": {
                "orderId":          order_id,
                "GlobalVendorCode": {"globalEntityId": "PY_AR",
                                     "vendorId": vendor_id},
            },
            "hasPhotoEvidence": False,
        },
        "query": _GQL_ORDER_DETAIL,
    }

    for intento in range(1, 3):          # hasta 2 intentos
        try:
            r = requests.post(PEYA_GQL_URL, headers=_h_gql(token),
                              json=body, timeout=60)
            r.raise_for_status()
            result = r.json()
            order_data = ((result.get("data") or {})
                          .get("orders", {})
                          .get("order", {}))
            if order_data:
                return order_data
            logger.debug(f"PedidosYa detalle {order_id}: respuesta vacía (intento {intento})")
        except Exception as e:
            logger.warning(f"PedidosYa detalle {order_id} intento {intento}: {e}")
        time.sleep(0.5)

    return {}


# ── CONVERTIR reclamos PedidosYa al modelo ────────────────────────────────────
def convertir_reclamos_peya(raw_lista: list[dict],
                             detalles: dict[str, dict]) -> list[Reclamo]:
    """
    Combina la lista de órdenes reclamadas con los detalles por orden.
    Si el detalle no está disponible, deja platos_pedidos vacío.
    """
    reclamos: list[Reclamo] = []

    for orden in raw_lista:
        oid       = str(orden.get("orderId", "")).strip()
        vendor_id = str(orden.get("vendorId", "")).strip()
        if not oid or not vendor_id:
            continue

        tienda = PY_INDEX.get(int(vendor_id)) if vendor_id.isdigit() else None
        if not tienda:
            logger.warning(f"PedidosYa reclamo: vendorId {vendor_id} no encontrado")
            continue

        fecha_s = str(orden.get("placedTimestamp", ""))
        fecha   = _parsear_fecha_peya(fecha_s) if fecha_s else datetime.now()

        # Detalle de la orden (de Query 2)
        detalle      = detalles.get(oid, {})
        order_detail = detalle.get("order", {}) or {}
        order_issues = detalle.get("orderIssues", []) or []

        # Platos pedidos
        items          = order_detail.get("items", []) or []
        nombres_items  = [it.get("name", "") for it in items if it.get("name")]
        platos_pedidos = " / ".join(nombres_items) if nombres_items else "(sin detalle)"

        # Motivo y comentario del cliente
        razones_list:     list[str] = []
        comentarios_list: list[str] = []

        for issue in order_issues:
            issue_type = issue.get("orderIssue", "")
            traducido  = PEYA_ISSUE_TRADUCCION.get(issue_type, issue_type)
            if traducido and traducido not in razones_list:
                razones_list.append(traducido)

            for meta in (issue.get("metadata") or []):
                reason = str(meta.get("reason", "") or "").strip()
                if reason and reason not in comentarios_list:
                    comentarios_list.append(reason)

        # Fallback de motivo: usar orderIssues de la lista (Query 1)
        if not razones_list:
            for raw_issue in (orden.get("orderIssues") or []):
                if isinstance(raw_issue, str):
                    raw_issue = raw_issue.strip()
                    val = PEYA_ISSUE_TRADUCCION.get(raw_issue, raw_issue)
                    if val and val not in razones_list:
                        razones_list.append(val)

        reclamos.append(Reclamo(
            orden_id          = oid,
            app               = "PedidosYa",
            marca             = tienda["marca"],
            local_id          = tienda["grupo"],
            local_nombre      = tienda["grupo"],
            fecha_orden       = fecha,
            platos_pedidos    = platos_pedidos,
            platos_reclamados = "",   # PedidosYa no identifica el ítem exacto reclamado
            razon             = " | ".join(razones_list),
            comentario        = " | ".join(comentarios_list),
        ))

    logger.info(f"PedidosYa reclamos convertidos: {len(reclamos)}")
    return reclamos




# ── API RESEÑAS ───────────────────────────────────────────────────────────────
def api_resenas_peya(token: str, vendor_codes: list[str],
                     desde: datetime, hasta: datetime) -> list[dict]:
    vendor_codes_prefijados = [f"PY_AR;{c}" for c in vendor_codes]
    body = {
        "global_vendor_codes": vendor_codes_prefijados,
        "pagination": {"perPage": 20000},
        "filter": {
            "hasText":   False,
            "startDate": _diso(desde),
            "endDate":   _diso(hasta),
        },
    }
    try:
        r = requests.post(REVIEWS_URL, headers=_h(token), json=body, timeout=60)
        logger.info(f"PedidosYa reviews — Status: {r.status_code}")
        r.raise_for_status()
        reviews = r.json().get("reviews", [])
        if reviews:
            sample = reviews[0]
            logger.info(f"PedidosYa reviews — keys del primer registro: {list(sample.keys())}")
            logger.info(f"PedidosYa reviews — rating: {sample.get('rating')}, vendorId: {sample.get('vendorId')}")
            prs = sample.get("product_ratings", [])
            logger.info(f"PedidosYa reviews — product_ratings count: {len(prs)}")
            if prs:
                logger.info(f"PedidosYa reviews — primer product_rating: {prs[0]}")
        logger.info(f"PedidosYa reviews API: {len(reviews)} registros")
        return reviews
    except Exception as e:
        logger.error(f"PedidosYa reviews API error: {e}")
        return []


# ── API TOTALES (browser) ─────────────────────────────────────────────────────
async def _fetch_performance_desde_browser(page, vendor_codes: list[str],
                                            desde: datetime, hasta: datetime) -> int:
    body = {
        "global_vendor_codes": vendor_codes,
        "from":      desde.strftime("%Y-%m-%d"),
        "to":        hasta.strftime("%Y-%m-%d"),
        "precision": "DAY",
    }
    import json as _json
    body_str = _json.dumps(body)
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
                    body: JSON.stringify({_json.loads(body_str)})
                }});
                const data = await r.json();
                return {{ status: r.status, data: data }};
            }} catch(e) {{
                return {{ status: 0, error: e.toString() }};
            }}
        }}
    """)
    if not result or result.get("status") != 200:
        logger.warning(f"PedidosYa perf browser: status={result.get('status')} error={result.get('error','')}")
        return 0
    data = result.get("data", {}).get("data", [])
    if isinstance(data, list):
        return sum(int(item.get("orderCount", 0)) for item in data)
    return 0


# ── CONVERSIÓN ────────────────────────────────────────────────────────────────
_TAG_TRADUCCION = {
    "SMALL_PORTION_SIZE":    "PORCIÓN REDUCIDA",
    "LOW_QUALITY":           "PROBLEMAS DE CALIDAD",
    "MISSING_OR_MISTAKEN":   "DISTINTO O INCOMPLETO",
    "BAD_TASTE":             "MAL SABOR",
    "WRONG_ORDER":           "PEDIDO INCORRECTO",
    "MISSING_ITEMS":         "FALTARON ALGUNOS ITEMS",
    "LATE_DELIVERY":         "TARDÓ MUCHO",
    "COLD_FOOD":             "LLEGÓ FRÍO",
    "BAD_PACKAGING":         "MAL EMBALAJE",
    "QUALITY_INGREDIENTS":   "PROBLEMAS DE CALIDAD",
    "OTHER":                 "OTRO",
}

def _parsear_fecha_peya(s: str) -> datetime:
    for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
        try:
            return datetime.strptime(s, fmt)
        except (ValueError, TypeError):
            pass
    logger.warning(f"PedidosYa: no se pudo parsear fecha '{s}'")
    return datetime.now()


def convertir_peya(raw: list[dict]) -> list[Resena]:
    resenas = []
    for rev in raw:
        orden_id        = str(rev.get("orderId") or rev.get("id") or "").strip()
        vendor_code_raw = str(rev.get("globalVendorCode", rev.get("vendorId", ""))).strip()
        vendor_id_num   = vendor_code_raw.split(";")[-1] if ";" in vendor_code_raw else vendor_code_raw
        fecha_s         = rev.get("date") or rev.get("createdAt") or rev.get("created_at") or ""
        fecha           = _parsear_fecha_peya(str(fecha_s)) if fecha_s else datetime.now()

        tienda = PY_INDEX.get(int(vendor_id_num)) if vendor_id_num.isdigit() else None
        if not tienda:
            logger.debug(f"PedidosYa: globalVendorCode {vendor_code_raw!r} no encontrado")
            continue

        rating_orden    = int(rev.get("rating", 0))
        product_ratings = rev.get("product_ratings", [])

        if not product_ratings:
            if rating_orden not in (1, 2):
                continue
            resenas.append(Resena(
                orden_id=orden_id, app="PedidosYa",
                marca=tienda["marca"], local_id=tienda["grupo"],
                local_nombre=tienda["grupo"], fecha_orden=fecha,
                estrellas=rating_orden, plato="(sin detalle de producto)",
                tags=[], comentario="",
            ))
            continue

        for pr in product_ratings:
            rating = int(pr.get("rating") or rating_orden or 0)
            if rating not in (1, 2):
                continue
            plato      = pr.get("name", "") or "(sin especificar)"
            comentario = pr.get("text", "") or ""
            raw_pills  = pr.get("dish_pills", [])
            tags = []
            for pill in raw_pills:
                if isinstance(pill, str) and pill:
                    tags.append(pill)
                elif isinstance(pill, dict):
                    tags.append(pill.get("name", pill.get("label", "")))
            tags = [_TAG_TRADUCCION.get(t, t) for t in tags if t]

            resenas.append(Resena(
                orden_id=orden_id, app="PedidosYa",
                marca=tienda["marca"], local_id=tienda["grupo"],
                local_nombre=tienda["grupo"], fecha_orden=fecha,
                estrellas=rating, plato=plato, tags=tags, comentario=comentario,
            ))

    logger.info(f"PedidosYa: {len(resenas)} reseñas negativas de {len(raw)} registros")
    return resenas


# ── FLUJO COMPLETO ────────────────────────────────────────────────────────────
async def extraer_pedidosya(desde: datetime, hasta: Optional[datetime] = None,
                             headless: bool = False
                             ) -> tuple[list[Resena], list[Reclamo], dict[str, int]]:
    if not hasta:
        hasta = datetime.now()

    def _fetch_reclamos(token: str, raw_lista_override: list[dict] | None = None) -> list[Reclamo]:
        """
        Obtiene y convierte los reclamos PedidosYa del período (síncrono).
        Si raw_lista_override no es None, se saltea la llamada de lista y usa ese valor.
        """
        raw_lista = raw_lista_override if raw_lista_override is not None \
                    else api_reclamos_lista_peya(token, ALL_PY_IDS, desde, hasta)
        detalles: dict[str, dict] = {}
        for orden in raw_lista:
            oid = str(orden.get("orderId", "")).strip()
            vid = str(orden.get("vendorId", "")).strip()
            ts  = str(orden.get("placedTimestamp", ""))
            if oid:
                detalles[oid] = api_reclamos_detalle_peya(token, oid, vid, ts)
        return convertir_reclamos_peya(raw_lista, detalles)

    token_env = os.environ.get("PEYA_TOKEN", "").strip()
    if token_env:
        logger.info(f"PedidosYa: usando token del entorno ({len(token_env)} chars)")
        access_token = token_env

        raw     = api_resenas_peya(access_token, ALL_PY_IDS, desde, hasta)
        resenas = convertir_peya(raw)

        # Prioridad 0: reclamos pre-calculados por el helper en el mismo browser
        reclamos_data_env = os.environ.get("PEYA_RECLAMOS_DATA", "").strip()
        if reclamos_data_env:
            try:
                raw_data = json.loads(reclamos_data_env)
                raw_lista_helper = [item["orden"]   for item in raw_data]
                detalles_helper  = {
                    str(item["orden"].get("orderId", "")): item["detalle"]
                    for item in raw_data
                }
                reclamos = convertir_reclamos_peya(raw_lista_helper, detalles_helper)
                logger.info(f"PedidosYa: reclamos del helper ({len(reclamos)} convertidos)")
            except Exception as e:
                logger.warning(f"PedidosYa: error leyendo PEYA_RECLAMOS_DATA — {e}")
                reclamos = []
        else:
            reclamos = _fetch_reclamos(access_token)
            # Si requests dio 403 (lista vacía), reintentar desde browser
            if not reclamos:
                logger.info("PedidosYa reclamos: requests vacío, intentando desde browser...")
                reclamos = await _fetch_reclamos_via_browser(desde, hasta)

        if not resenas and not reclamos:
            logger.info("PedidosYa: sin reseñas ni reclamos en el período")
            return [], [], {}

        grupos_con_datos = list(
            {r.local_id for r in resenas} | {r.local_id for r in reclamos}
        )

        # Prioridad 1: totales pre-calculados por el helper (early return)
        totales_env = os.environ.get("PEYA_TOTALES", "").strip()
        if totales_env:
            import json as _json
            try:
                totales_pre = _json.loads(totales_env)
                totales = {g: totales_pre.get(g, 0) for g in grupos_con_datos}
                logger.info(f"PedidosYa: totales del helper para {len(totales)} grupos")
                for g, n in totales.items():
                    logger.info(f"PedidosYa totales '{g}': {n} órdenes")
                return resenas, reclamos, totales
            except Exception as e:
                logger.warning(f"PedidosYa: error leyendo PEYA_TOTALES — {e}")

        # Prioridad 2: browser con storage_state para totales
        totales = {}
        state_file = os.environ.get("PEYA_STATE_FILE", "")
        ctx_kwargs = dict(
            viewport={"width": 1280, "height": 800}, locale="es-AR",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        if state_file and Path(state_file).exists():
            ctx_kwargs["storage_state"] = state_file
            logger.info("PedidosYa totales: restaurando estado del browser")
        else:
            logger.warning("PedidosYa totales: sin estado guardado — puede dar 403")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True, slow_mo=200,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            page = await (await browser.new_context(**ctx_kwargs)).new_page()
            await page.goto("https://portal-app.pedidosya.com", wait_until="domcontentloaded")
            for grupo in grupos_con_datos:
                vc = [f"PY_AR;{t['py_id']}" for t in TIENDAS
                      if t["grupo"] == grupo and t["py_id"]]
                total = await _fetch_performance_desde_browser(page, vc, desde, hasta)
                totales[grupo] = total
                logger.info(f"PedidosYa totales '{grupo}': {total} órdenes")
            await browser.close()

        return resenas, reclamos, totales

    else:
        # Sin token en entorno — flujo manual (consola sin GUI)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=False, slow_mo=200,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            page = await (await browser.new_context(
                viewport={"width": 1280, "height": 800}, locale="es-AR",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            )).new_page()

            logger.info("PedidosYa: abriendo portal de login...")
            await page.goto(LOGIN_URL, wait_until="networkidle")

            print("\n" + "="*60)
            print("PEDIDOSYA: Completá el login en el browser que se abrió.")
            print("Presioná ENTER cuando estés dentro del portal.")
            print("="*60)
            input()

            await page.wait_for_timeout(2000)
            access_token = await page.evaluate("""
                (() => {
                    try {
                        const root = localStorage.getItem('persist:root');
                        if (!root) return null;
                        const auth = JSON.parse(JSON.parse(root).authentication);
                        return auth.accessToken || null;
                    } catch(e) { return null; }
                })()
            """)

            if not access_token:
                raise RuntimeError("PedidosYa: no se encontró el token")
            logger.info(f"PedidosYa: token OK ({len(access_token)} chars)")

            raw     = api_resenas_peya(access_token, ALL_PY_IDS, desde, hasta)
            resenas = convertir_peya(raw)

            reclamos = _fetch_reclamos(access_token)

            # Si requests da 403, usar el browser ya abierto y autenticado
            if not reclamos:
                logger.info("PedidosYa reclamos: requests vacío, intentando desde browser...")
                raw_browser = await _api_reclamos_lista_desde_browser(
                    page, access_token, ALL_PY_IDS, desde, hasta)
                if raw_browser:
                    detalles_browser: dict[str, dict] = {}
                    for orden in raw_browser:
                        oid = str(orden.get("orderId", "")).strip()
                        vid = str(orden.get("vendorId", "")).strip()
                        ts  = str(orden.get("placedTimestamp", ""))
                        if oid:
                            det = api_reclamos_detalle_peya(access_token, oid, vid, ts)
                            if not det:
                                det = await _api_reclamos_detalle_desde_browser(
                                    page, oid, vid, ts)
                            detalles_browser[oid] = det
                    reclamos = convertir_reclamos_peya(raw_browser, detalles_browser)

            if not resenas and not reclamos:
                logger.info("PedidosYa: sin reseñas ni reclamos en el período")
                await browser.close()
                return [], [], {}

            grupos_con_datos = list(
                {r.local_id for r in resenas} | {r.local_id for r in reclamos}
            )
            totales = {}
            for grupo in grupos_con_datos:
                vc = [f"PY_AR;{t['py_id']}" for t in TIENDAS
                      if t["grupo"] == grupo and t["py_id"]]
                total = await _fetch_performance_desde_browser(page, vc, desde, hasta)
                totales[grupo] = total
                logger.info(f"PedidosYa totales '{grupo}': {total} órdenes")

            await browser.close()
        return resenas, reclamos, totales


# ── Test standalone ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s")
    asyncio.run(extraer_pedidosya(
        desde=datetime.now() - timedelta(days=1),
    ))
