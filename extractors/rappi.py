"""
Extractor Rappi — flujo real.
  1. Playwright → partners.rappi.com/login → localStorage.access_token
  2. api_resenas: paginación automática, filtra 1-2 estrellas
  3. api_ordenes: llamada MASIVA (una sola request con todos los order_ids)
     para obtener nombre de platos y tienda
"""
import asyncio, logging, requests, time
from datetime import datetime, timedelta
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from config.models import Resena, Reclamo
from config.locales import RAPPI_INDEX, ALL_RAPPI_IDS, ALL_RAPPI_IDS_AR

logger = logging.getLogger(__name__)

REVIEWS_URL   = ("https://services.rappi.com/rests-partners-gateway/cauth/"
                 "api/support-ratings/reviews/details/partner?country=AR")
ORDERS_URL    = ("https://services.rappi.com/rests-partners-gateway/cauth/"
                 "rests-stores-config/orders/by-stores?country=AR")
COMP_SALES_URL = ("https://services.rappi.com/rests-partners-gateway/cauth/"
                  "api/settlement-financial/v1/stores/sales?country=AR")
COMP_URL       = ("https://services.rappi.com/rests-partners-gateway/cauth/"
                  "api/settlement-financial/v1/stores/compensations?country=AR")

# Traducción de motivos de reclamo (inglés → español)
RAZON_TRADUCCION = {
    "product_poor":       "NO LLEGÓ EN BUENAS CONDICIONES",
    "product_missing":    "INCOMPLETO",
    "product_difference": "INCORRECTO O DIFERENTE A LO ESPERADO",
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _h(token): return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
def _d(dt):    return dt.strftime("%Y-%m-%d")
def _dh(dt):   return dt.strftime("%Y-%m-%d %H:%M:%S")


# ── LOGIN ─────────────────────────────────────────────────────────────────────
async def obtener_token(email: str, password: str, headless=True) -> str:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless, slow_mo=300,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
        page = await (await browser.new_context(
            viewport={"width": 1280, "height": 800}, locale="es-AR",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )).new_page()

        await page.goto("https://partners.rappi.com/login", wait_until="networkidle")
        await page.wait_for_selector('input[type="email"]', timeout=15_000)
        await page.fill('input[type="email"]', email)
        await page.fill('input[type="password"]', password)
        await page.click('button[type="submit"]')

        logger.info("Rappi: esperando token en localStorage...")
        try:
            await page.wait_for_function(
                "window.localStorage.getItem('access_token') !== null", timeout=30_000)
        except PWTimeout:
            logger.warning("Rappi: token no apareció en 30s — esperando 60s (¿CAPTCHA?)")
            await page.wait_for_timeout(60_000)

        token = await page.evaluate("window.localStorage.getItem('access_token')")
        if not token:
            await page.screenshot(path="/tmp/rappi_login_error.png")
            raise RuntimeError("Rappi: no se obtuvo access_token")

        await browser.close()
        logger.info(f"Rappi: token OK ({len(token)} chars)")
        return token


# ── API RESEÑAS (con paginación) ──────────────────────────────────────────────
def api_resenas(token, store_ids, desde, hasta) -> list[dict]:
    """
    Trae todas las reseñas de 1-2 estrellas paginando automáticamente.
    La API devuelve 20 por página; seguimos hasta que venga una página vacía
    o con menos de per_page registros.
    """
    all_reviews = []
    page        = 1
    per_page    = 20

    while True:
        body = {
            "store_ids":  store_ids,
            "start_date": _dh(desde),
            "end_date":   _dh(hasta),
            "scores":     [1, 2],
            "per_page":   per_page,
            "page":       page,
        }
        r = requests.post(REVIEWS_URL, headers=_h(token), json=body, timeout=60)
        r.raise_for_status()

        reviews = r.json().get("data", {}).get("reviews", [])
        logger.info(f"Rappi reviews pág {page}: {len(reviews)} registros")

        if not reviews:
            break

        all_reviews.extend(reviews)

        if len(reviews) < per_page:
            break  # última página

        page += 1

    logger.info(f"Rappi reviews total: {len(all_reviews)}")
    return all_reviews


# ── API ÓRDENES (llamada masiva) ──────────────────────────────────────────────
def api_ordenes(token, desde, hasta, order_ids: list[str]) -> dict[str, dict]:
    """
    Busca el detalle de cada orden de a una por vez (límite de la API).

    - store_ids requiere prefijo "AR" → usamos ALL_RAPPI_IDS_AR
    - order_id en el body: el número limpio "460045241" (sin prefijo)
    - La API devuelve el id con prefijo "AR460045241" en la respuesta

    Retorna dict { order_id_SIN_prefijo → detalle } para matchear con resenas.
    """
    if not order_ids:
        return {}

    mapa: dict[str, dict] = {}

    for oid in order_ids:
        oid_limpio = str(oid).strip()
        if not oid_limpio:
            continue

        body = {
            "country_code": "AR",
            "from":         _d(desde),
            "to":           _d(hasta),
            "store_ids":    ALL_RAPPI_IDS_AR,   # requiere prefijo "AR"
            "language":     "es",
            "page_number":  0,
            "page_size":    1,
            "order_id":     oid_limpio,          # número limpio, sin "AR"
        }

        try:
            r = requests.post(ORDERS_URL, headers=_h(token), json=body, timeout=60)
            r.raise_for_status()
            results = r.json().get("results", [])
        except Exception as e:
            logger.error(f"Rappi ordenes: error en orden {oid_limpio}: {e}")
            continue

        if not results:
            logger.debug(f"Rappi ordenes: sin resultado para orden {oid_limpio}")
            continue

        det = results[0]

        platos = [
            {
                "nombre":   item.get("product_name", ""),
                "cantidad": item.get("units", 1),
                "toppings": item.get("toppings", []),
            }
            for item in det.get("order_product_details", [])
        ]

        mapa[oid_limpio] = {
            "tienda": det.get("store_name", ""),
            "platos": platos,
        }

        time.sleep(0.5)   # pausa reducida a 0.5s — suficiente para no saturar la API

    logger.info(f"Rappi ordenes: {len(mapa)} recuperadas de {len(order_ids)} buscadas")
    return mapa


# ── CONVERTIR reseñas crudas al modelo ───────────────────────────────────────
def convertir(raw: list[dict]) -> list[Resena]:
    """
    Convierte raw de api_resenas a lista de Resena.
    Campos conocidos: order_id, store_id, created_at, score, option, rating_type
    """
    por_orden: dict[str, list] = {}
    for r in raw:
        por_orden.setdefault(str(r.get("order_id", "")), []).append(r)

    resenas = []
    for orden_id, items in por_orden.items():
        score = int(items[0].get("score", 0))
        if score not in (1, 2):
            continue

        sid    = items[0].get("store_id")
        tienda = RAPPI_INDEX.get(int(sid)) if sid else None
        if not tienda:
            logger.warning(f"Rappi: store_id {sid} no encontrado en config")
            continue

        # fecha
        fecha_s = str(items[0].get("created_at", ""))
        fecha   = datetime.now()
        for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
            try:
                fecha = datetime.strptime(fecha_s, fmt)
                break
            except ValueError:
                pass
        else:
            logger.warning(f"Rappi: no se pudo parsear fecha '{fecha_s}' — usando ahora")

        # tags (etiquetas rápidas)
        tags = list({i.get("option", "") for i in items if i.get("option")})

        # plato desde rating_type (nombre del ítem calificado)
        # Filtrar valores internos de Rappi que no son nombres de productos
        VALORES_INTERNOS = {"", "order", "general", "RATE_AND_REVIEW_STARS",
                            "RATE_AND_REVIEW_STORE", "RATE_AND_REVIEW_DELIVERY", None}
        platos_rt = [i.get("rating_type", "") for i in items
                     if i.get("rating_type") not in VALORES_INTERNOS]
        plato_inicial = platos_rt[0] if platos_rt else ""

        resenas.append(Resena(
            orden_id=orden_id,
            app="Rappi",
            marca=tienda["marca"],
            local_id=tienda["grupo"],
            local_nombre=tienda["grupo"],
            fecha_orden=fecha,
            estrellas=score,
            plato=plato_inicial,
            tags=tags,
            comentario="",
        ))

    logger.info(f"Rappi: {len(resenas)} reseñas negativas de {len(raw)} totales")
    return resenas


# ── API RECLAMOS — paso 1: órdenes compensadas (con paginación) ───────────────
def api_reclamos_ordenes(token, store_ids, desde, hasta) -> list[dict]:
    """
    Trae todas las órdenes con status COMPENSATIONS paginando automáticamente.
    Retorna lista de entries con {order_id, order_date, store_id, store_name, ...}.
    """
    all_entries = []
    page        = 1
    per_page    = 50

    while True:
        body = {
            "page_number":     page,
            "page_size":       per_page,
            "order_status:eq": ["COMPENSATIONS"],
            "store_ids":       store_ids,
            "order_date:gte":  _d(desde),
            "order_date:lte":  _d(hasta),
        }
        r = requests.post(COMP_SALES_URL, headers=_h(token), json=body, timeout=60)
        r.raise_for_status()

        entries = r.json().get("entries", [])
        logger.info(f"Rappi reclamos órdenes pág {page}: {len(entries)} registros")

        if not entries:
            break

        all_entries.extend(entries)

        if len(entries) < per_page:
            break

        page += 1

    logger.info(f"Rappi reclamos: {len(all_entries)} órdenes compensadas en total")
    return all_entries


# ── API RECLAMOS — paso 2: detalle de compensaciones por orden ────────────────
def api_reclamos_detalles(token, store_ids, order_ids: list[str]) -> dict[str, list]:
    """
    Para cada order_id consulta el endpoint de compensations y obtiene los detalles.
    Retorna dict { order_id → lista de compensations [{products_names, reason, ...}] }.
    """
    if not order_ids:
        return {}

    detalles: dict[str, list] = {}

    for oid in order_ids:
        oid_str = str(oid).strip()
        body = {
            "store_ids":   store_ids,
            "order_ids":   [oid_str],
            "page_number": 1,
            "page_size":   1,
        }
        try:
            r = requests.post(COMP_URL, headers=_h(token), json=body, timeout=60)
            r.raise_for_status()
            entries = r.json().get("entries", [])
        except Exception as e:
            logger.error(f"Rappi reclamo detalle {oid_str}: {e}")
            continue

        if entries:
            detalles[oid_str] = entries[0].get("compensations", [])
        else:
            detalles[oid_str] = []

        time.sleep(0.25)

    logger.info(f"Rappi reclamos detalles: {len(detalles)} obtenidos de {len(order_ids)} buscados")
    return detalles


# ── CONVERTIR reclamos crudos al modelo ───────────────────────────────────────
def convertir_reclamos(raw_ordenes: list[dict],
                       detalles: dict[str, list],
                       mapa_ordenes: dict[str, dict]) -> list[Reclamo]:
    """
    Combina:
      - raw_ordenes:  lista de entries de COMP_SALES_URL (una fila por orden compensada)
      - detalles:     dict order_id → compensations del COMP_URL
      - mapa_ordenes: dict order_id → {tienda, platos} de api_ordenes (ya existente)
    """
    reclamos = []

    for orden in raw_ordenes:
        oid = str(orden.get("order_id", "")).strip()
        if not oid:
            continue

        sid    = orden.get("store_id")
        tienda = RAPPI_INDEX.get(int(sid)) if sid else None
        if not tienda:
            logger.warning(f"Rappi reclamo: store_id {sid} no encontrado en config")
            continue

        # ── Fecha ──────────────────────────────────────────────────────────────
        fecha_s = str(orden.get("order_date", ""))
        fecha   = datetime.now()
        for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
            try:
                fecha = datetime.strptime(fecha_s, fmt)
                break
            except ValueError:
                pass

        # ── Platos pedidos (de la misma api_ordenes usada en reseñas) ──────────
        detalle_orden = mapa_ordenes.get(oid)
        if detalle_orden and detalle_orden.get("platos"):
            nombres = [p["nombre"] for p in detalle_orden["platos"] if p["nombre"]]
            platos_pedidos = " / ".join(nombres) if nombres else "(sin detalle)"
        else:
            platos_pedidos = "(sin detalle)"

        # ── Detalles del reclamo (products_names + reason + user_details) ───────
        compensaciones = detalles.get(oid, [])
        platos_reclamados_list: list[str] = []
        razones_list:           list[str] = []
        comentarios_list:       list[str] = []

        for comp in compensaciones:
            for prod in comp.get("products_names", []):
                if prod and prod not in platos_reclamados_list:
                    platos_reclamados_list.append(prod)

            reason_raw = comp.get("reason", "")
            reason     = RAZON_TRADUCCION.get(reason_raw, reason_raw)
            if reason and reason not in razones_list:
                razones_list.append(reason)

            user_comment = str(comp.get("user_details", "") or "").strip()
            if user_comment and user_comment not in comentarios_list:
                comentarios_list.append(user_comment)

        reclamos.append(Reclamo(
            orden_id          = oid,
            app               = "Rappi",
            marca             = tienda["marca"],
            local_id          = tienda["grupo"],
            local_nombre      = tienda["grupo"],
            fecha_orden       = fecha,
            platos_pedidos    = platos_pedidos,
            platos_reclamados = " / ".join(platos_reclamados_list) if platos_reclamados_list else "",
            razon             = " | ".join(razones_list) if razones_list else "",
            comentario        = " | ".join(comentarios_list) if comentarios_list else "",
        ))

    logger.info(f"Rappi reclamos convertidos: {len(reclamos)}")
    return reclamos


# ── FLUJO COMPLETO ────────────────────────────────────────────────────────────
async def extraer_rappi(email, password, fecha_desde, fecha_hasta=None, headless=True):
    """
    Retorna (resenas, reclamos, totales_por_grupo).
    - resenas:  reseñas negativas (1-2 estrellas) con .plato enriquecido
    - reclamos: órdenes compensadas con platos pedidos y reclamados
    - totales_por_grupo: dict grupo → cantidad de órdenes totales (denominador del índice)
    """
    if not fecha_hasta:
        fecha_hasta = datetime.now()

    token = await obtener_token(email, password, headless)

    # 1. Reseñas (con paginación)
    raw     = api_resenas(token, ALL_RAPPI_IDS, fecha_desde, fecha_hasta)
    resenas = convertir(raw)

    # 2. Reclamos — paso 1: órdenes compensadas
    logger.info("── Rappi: extrayendo reclamos (COMPENSATIONS)...")
    raw_reclamos = api_reclamos_ordenes(token, ALL_RAPPI_IDS, fecha_desde, fecha_hasta)

    # 3. Detalle de órdenes unificado: incluye order_ids de reseñas Y de reclamos
    #    Una sola pasada por api_ordenes para obtener todos los platos de una vez.
    order_ids_resenas  = [r.orden_id for r in resenas]
    order_ids_reclamos = [str(e.get("order_id", "")) for e in raw_reclamos if e.get("order_id")]
    # Unión sin duplicados, preservando orden
    order_ids_todos = list(dict.fromkeys(order_ids_resenas + order_ids_reclamos))

    mapa_ordenes: dict[str, dict] = {}
    if order_ids_todos:
        mapa_ordenes = api_ordenes(token, fecha_desde, fecha_hasta, order_ids_todos)

    # 4. Enriquecer reseñas con nombre real del plato
    enriquecidas = 0
    for r in resenas:
        detalle = mapa_ordenes.get(r.orden_id)
        if detalle and detalle["platos"]:
            nombres = [p["nombre"] for p in detalle["platos"] if p["nombre"]]
            if nombres:
                r.plato = " / ".join(nombres)
                enriquecidas += 1
        elif not r.plato:
            r.plato = "(sin detalle de producto)"

    logger.info(f"Rappi: {enriquecidas}/{len(resenas)} reseñas enriquecidas con nombre de plato")

    # 5. Reclamos — paso 2: detalles de compensación por orden
    detalles_reclamos: dict[str, list] = {}
    if order_ids_reclamos:
        detalles_reclamos = api_reclamos_detalles(token, ALL_RAPPI_IDS, order_ids_reclamos)

    # 6. Convertir reclamos al modelo
    reclamos = convertir_reclamos(raw_reclamos, detalles_reclamos, mapa_ordenes)

    # 7. Totales por grupo (denominador del índice)
    grupos_con_actividad = list({r.local_id for r in resenas} | {rc.local_id for rc in reclamos})
    totales_grupo = calcular_totales_por_grupo(token, grupos_con_actividad, fecha_desde, fecha_hasta)

    return resenas, reclamos, totales_grupo


SALES_URL = ("https://services.rappi.com/rests-partners-gateway/cauth/"
             "partners-indicators/indicator/sales/prime?previous=true")


def calcular_total_ordenes_grupo(token, grupo: str, desde, hasta) -> int:
    """
    Devuelve el total de órdenes de UN grupo/local en el período.
    Se llama una vez por grupo para calcular el denominador del índice.

    El body usa los store_ids (con prefijo AR) de las tiendas de ese grupo.
    """
    from config.locales import TIENDAS

    # IDs de todas las tiendas que pertenecen a este grupo
    store_ids_grupo = [
        f"AR{t['rappi_id']}"
        for t in TIENDAS
        if t["grupo"] == grupo and t["rappi_id"]
    ]

    if not store_ids_grupo:
        logger.warning(f"Rappi totales: grupo '{grupo}' sin tiendas configuradas")
        return 0

    body = {
        "country_code": "AR",
        "from":         _d(desde),
        "to":           _d(hasta),
        "store_ids":    store_ids_grupo,
    }

    try:
        r = requests.post(SALES_URL, headers=_h(token), json=body, timeout=60)
        r.raise_for_status()
        raw = r.json()
    except Exception as e:
        logger.error(f"Rappi totales grupo '{grupo}': {e}")
        return 0

    # La API devuelve el objeto directo en la raíz o bajo "data"
    # Cubrimos ambas posibilidades y logueamos para confirmar
    if "total_orders" in raw:
        total = raw["total_orders"]
    elif "data" in raw and isinstance(raw["data"], dict):
        total = raw["data"].get("total_orders", 0)
    else:
        total = 0
        logger.warning(f"Rappi totales '{grupo}': no se encontró total_orders")
        logger.warning(f"  Keys raíz: {list(raw.keys())}")
        if "data" in raw:
            logger.warning(f"  Keys de data: {list(raw['data'].keys()) if isinstance(raw['data'], dict) else type(raw['data'])}")

    logger.info(f"Rappi totales '{grupo}': {total} órdenes")
    return int(total)


def calcular_totales_por_grupo(token, grupos: list[str], desde, hasta) -> dict[str, int]:
    """
    Llama a calcular_total_ordenes_grupo para cada grupo y devuelve el dict completo.
    """
    totales = {}
    for grupo in grupos:
        totales[grupo] = calcular_total_ordenes_grupo(token, grupo, desde, hasta)
        time.sleep(0.3)   # pequeña pausa entre llamadas
    return totales


# ── Test standalone ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s")
    asyncio.run(extraer_rappi(
        os.getenv("RAPPI_EMAIL",    "u@e.com"),
        os.getenv("RAPPI_PASSWORD", "pass"),
        datetime.now() - timedelta(days=1),
        headless=False,
    ))
