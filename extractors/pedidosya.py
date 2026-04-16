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

Reclamos:
  - Se obtienen desde un webhook de n8n que devuelve un CSV.
  - Usar descargar_reclamos_peya_webhook() + parsear_reclamos_peya_webhook().
"""
import asyncio, csv, logging, os, re, sys
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


# ── Helpers ───────────────────────────────────────────────────────────────────
def _h(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def _diso(dt: datetime) -> str:
    """Formato ISO que usa PedidosYa: 2026-03-31T03:00:00.000Z"""
    return dt.strftime("%Y-%m-%dT03:00:00.000Z")


# ── Matching de nombres de tienda PedidosYa ───────────────────────────────────

def _normalizar(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()

# Índice normalizado: nombre → tienda (todas las marcas, con o sin py_id)
_PY_NOMBRE_INDEX: dict[str, dict] = {}
for _t in TIENDAS:
    _PY_NOMBRE_INDEX[_normalizar(_t["nombre"])] = _t

def _buscar_tienda_peya(partner_name: str) -> dict | None:
    """Busca tienda por nombre con matching tolerante a variaciones tipográficas."""
    norm = _normalizar(partner_name)

    # 1. Match exacto normalizado
    if norm in _PY_NOMBRE_INDEX:
        return _PY_NOMBRE_INDEX[norm]

    # 2. Match parcial
    for key, tienda in _PY_NOMBRE_INDEX.items():
        if norm in key or key in norm:
            return tienda

    # 3. Match por palabras clave (>=2 palabras significativas en común)
    stop = {"de", "la", "el", "las", "los", "y"}
    palabras = set(norm.split()) - stop
    best, best_score = None, 0
    for key, tienda in _PY_NOMBRE_INDEX.items():
        score = len(palabras & (set(key.split()) - stop))
        if score > best_score and score >= 2:
            best_score, best = score, tienda

    return best


# ── Traducción de motivos del webhook ────────────────────────────────────────
PEYA_WEBHOOK_MOTIVO: dict[str, str] = {
    "missing item":  "INCOMPLETOS",
    "wrong item":    "EQUIVOCADOS",
    "wrong order":   "EQUIVOCADOS",
    "food quality":  "CALIDAD",
}

def _traducir_motivo(raw: str) -> str:
    return PEYA_WEBHOOK_MOTIVO.get(raw.strip().lower(), raw.strip().upper() or "(no especificado)")


# ── Descarga y parseo de reclamos desde webhook n8n ──────────────────────────

def descargar_reclamos_peya_webhook(url: str, carpeta: str = "./pedidosya") -> str:
    """
    Descarga el CSV de reclamos PedidosYa desde el webhook de n8n.

    Args:
        url:     URL del webhook (ej: https://xxx.app.n8n.cloud/webhook/...)
        carpeta: carpeta donde guardar el archivo (default: ./pedidosya)

    Returns:
        Ruta al archivo CSV descargado.

    Raises:
        RuntimeError: si la descarga falla o la respuesta no es un CSV válido.
    """
    import urllib.request, urllib.error

    carpeta_path = Path(carpeta)
    carpeta_path.mkdir(parents=True, exist_ok=True)

    fecha_str    = datetime.now().strftime("%Y%m%d")
    ruta_destino = str(carpeta_path / f"reclamos_peya_{fecha_str}.csv")

    logger.info("PedidosYa reclamos: descargando desde webhook n8n...")

    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            contenido = response.read()
    except urllib.error.URLError as e:
        raise RuntimeError(f"PedidosYa reclamos: no se pudo conectar al webhook: {e}")

    muestra = contenido[:512].decode("utf-8-sig", errors="replace")
    if "," not in muestra and ";" not in muestra:
        raise RuntimeError(
            f"PedidosYa reclamos: la respuesta del webhook no parece un CSV válido. "
            f"Primeros 200 chars: {muestra[:200]}"
        )

    with open(ruta_destino, "wb") as f:
        f.write(contenido)

    logger.info(f"PedidosYa reclamos: descargado → {ruta_destino} ({len(contenido):,} bytes)")
    return ruta_destino


def parsear_reclamos_peya_webhook(
    ruta_csv: str,
    fecha_desde: datetime,
    fecha_hasta: datetime,
) -> list[Reclamo]:
    """
    Parsea el CSV de reclamos PedidosYa proveniente del webhook de n8n.

    Columnas del CSV:
      order_id_general  → orden_id  (0 = ítem adicional de la orden anterior)
      partner_name      → nombre del restaurante (para buscar tienda)
      registered_date   → fecha del reclamo (se combina con hora_minutos)
      hora_minutos      → hora del reclamo (complementa registered_date)
      motivo            → motivo: "missing item"→INCOMPLETOS,
                          "wrong item"/"wrong order"→EQUIVOCADOS, "food quality"→CALIDAD
      producto          → nombre del plato
      comentarios       → comentario del cliente

    Las filas con order_id_general=0 son ítems adicionales de la orden anterior:
    su producto se concatena al campo platos_pedidos con " / ". Como no es posible
    determinar cuál fue el plato reclamado, platos_reclamados se deja en blanco.
    """
    ruta = Path(ruta_csv)
    if not ruta.exists():
        raise FileNotFoundError(f"PedidosYa reclamos: no se encontró '{ruta_csv}'")

    logger.info(f"PedidosYa reclamos: procesando '{ruta.name}'")

    reclamos   = []
    sin_tienda = []
    filtradas  = 0

    def _parsear_fecha_reclamo(fecha_str: str, hora_str: str, fila: int):
        fecha_hora_str = f"{fecha_str} {hora_str}".strip() if hora_str else fecha_str
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(fecha_hora_str, fmt)
            except ValueError:
                continue
        logger.warning(f"PedidosYa reclamos fila {fila}: no se pudo parsear fecha '{fecha_hora_str}'")
        return datetime.now().replace(hour=0, minute=0, second=0)

    def _finalizar_orden(pending: dict) -> None:
        """Intenta convertir la orden acumulada en un Reclamo y agregarlo a la lista."""
        if not pending:
            return

        # Filtro de fechas
        fecha = pending["fecha"]
        if fecha_desde and fecha.date() < fecha_desde.date():
            filtradas_ref[0] += 1
            return
        if fecha_hasta and fecha.date() > fecha_hasta.date():
            filtradas_ref[0] += 1
            return

        # Tienda
        tienda = _buscar_tienda_peya(pending["partner_name"])
        if not tienda:
            sin_tienda.append(pending["partner_name"])
            logger.warning(
                f"PedidosYa reclamos fila {pending['fila']}: "
                f"tienda no encontrada '{pending['partner_name']}'"
            )
            return

        platos = " / ".join(p for p in pending["productos"] if p)

        reclamos.append(Reclamo(
            orden_id          = pending["orden_id"],
            app               = "PedidosYa",
            marca             = tienda["marca"],
            local_id          = tienda["grupo"],
            local_nombre      = tienda["grupo"],
            fecha_orden       = fecha,
            platos_pedidos    = platos or "(no especificado)",
            platos_reclamados = "",   # no determinable cuando hay múltiples ítems
            razon             = pending["razon"],
            comentario        = pending["comentario"],
        ))

    # Contador mutable para poder modificar desde la función interna
    filtradas_ref = [0]
    pending: dict = {}

    with open(ruta, encoding="utf-8-sig", errors="replace") as f:
        muestra = f.read(2048); f.seek(0)
        delim = "," if muestra.count(",") > muestra.count(";") else ";"
        reader = csv.DictReader(f, delimiter=delim)

        for i, row in enumerate(reader, 2):
            if not any(v.strip() for v in row.values()):
                continue

            # Normalizar claves a minúsculas para tolerar variaciones de mayúsculas
            row_lower = {k.strip().lower(): v for k, v in row.items()}

            def col(nombre, default=""):
                return row_lower.get(nombre.lower(), "").strip() or default

            order_id_raw = col("order_id_general")
            partner_name = col("partner_name")

            # ── Fila secundaria (ítem adicional de la orden anterior) ─────
            if order_id_raw == "0" or not partner_name:
                if pending:
                    plato_extra = col("producto")
                    if plato_extra:
                        pending["productos"].append(plato_extra)
                continue

            # ── Fila principal (nueva orden) ──────────────────────────────
            # Finalizar la orden acumulada anterior (si existe)
            _finalizar_orden(pending)

            # Iniciar nueva orden acumulada
            fecha = _parsear_fecha_reclamo(col("registered_date"), col("hora_minutos"), i)
            plato = col("producto")
            pending = {
                "fila":         i,
                "orden_id":     order_id_raw or f"PY-R{i:04d}",
                "partner_name": partner_name,
                "fecha":        fecha,
                "razon":        _traducir_motivo(col("motivo")),
                "comentario":   col("comentarios"),
                "productos":    [plato] if plato else [],
            }

        # Finalizar la última orden acumulada
        _finalizar_orden(pending)

    filtradas = filtradas_ref[0]
    logger.info(
        f"PedidosYa reclamos: {len(reclamos)} importados — "
        f"{filtradas} fuera del período — "
        f"{len(sin_tienda)} tiendas no encontradas"
    )
    if sin_tienda:
        logger.warning(f"PedidosYa reclamos: tiendas sin match: {list(set(sin_tienda))}")

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
                             ) -> tuple[list[Resena], list, dict[str, int]]:
    """
    Extrae reseñas y totales de PedidosYa.
    Los reclamos se obtienen por separado mediante el webhook de n8n
    (ver descargar_reclamos_peya_webhook / parsear_reclamos_peya_webhook).
    Siempre devuelve lista de reclamos vacía.
    """
    if not hasta:
        hasta = datetime.now()

    token_env = os.environ.get("PEYA_TOKEN", "").strip()
    if token_env:
        logger.info(f"PedidosYa: usando token del entorno ({len(token_env)} chars)")
        access_token = token_env

        raw     = api_resenas_peya(access_token, ALL_PY_IDS, desde, hasta)
        resenas = convertir_peya(raw)

        if not resenas:
            logger.info("PedidosYa: sin reseñas en el período")
            return [], [], {}

        grupos_con_datos = list({r.local_id for r in resenas})

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
                return resenas, [], totales
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

        return resenas, [], totales

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

            if not resenas:
                logger.info("PedidosYa: sin reseñas en el período")
                await browser.close()
                return [], [], {}

            grupos_con_datos = list({r.local_id for r in resenas})
            totales = {}
            for grupo in grupos_con_datos:
                vc = [f"PY_AR;{t['py_id']}" for t in TIENDAS
                      if t["grupo"] == grupo and t["py_id"]]
                total = await _fetch_performance_desde_browser(page, vc, desde, hasta)
                totales[grupo] = total
                logger.info(f"PedidosYa totales '{grupo}': {total} órdenes")

            await browser.close()
        return resenas, [], totales


# ── Test standalone ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s")
    asyncio.run(extraer_pedidosya(
        desde=datetime.now() - timedelta(days=1),
    ))
