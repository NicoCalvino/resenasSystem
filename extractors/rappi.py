"""
Extractor Rappi — flujo real.
  1. Playwright → partners.rappi.com/login → localStorage.access_token
  2. api_resenas: paginación automática, filtra 1-2 estrellas
  3. api_ordenes: detalle de cada orden (de a una) para enriquecer reseñas
     con nombres reales de los platos.
  4. api_defects: endpoint /partners-indicators/indicators/defects para
     reclamos. Se llama una vez por (store_id × tipo_defecto) para
     garantizar el mapeo store_id → local sin depender de store_name.
"""
import asyncio, logging, requests, time
from datetime import datetime, timedelta
from typing import Optional

from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from config.models import Resena, Reclamo
from config.locales import RAPPI_INDEX, ALL_RAPPI_IDS, ALL_RAPPI_IDS_AR

logger = logging.getLogger(__name__)

REVIEWS_URL = ("https://services.rappi.com/rests-partners-gateway/cauth/"
               "api/support-ratings/reviews/details/partner?country=AR")
ORDERS_URL  = ("https://services.rappi.com/rests-partners-gateway/cauth/"
               "rests-stores-config/orders/by-stores?country=AR")
DEFECTS_URL = ("https://services.rappi.com/rests-partners-gateway/cauth/"
               "partners-indicators/indicators/defects")

# Tipos de defecto soportados por el endpoint /defects.
# Cada tipo se traduce a una razón en español que es la que ve el restaurante.
TIPO_A_RAZON = {
    "ERROR_MISSING": "INCOMPLETO",
    "ERROR_WRONG":   "EQUIVOCADO",
    "ERROR_DAMAGED": "CALIDAD",
}
TIPOS_DEFECTO = list(TIPO_A_RAZON.keys())


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
            if headless:
                # Captcha detectado en modo silencioso: reabrir el browser en modo visible
                # para que el usuario pueda completarlo manualmente.
                logger.warning("Rappi: captcha detectado — reabriendo navegador en modo visible")
                await browser.close()
                return await obtener_token(email, password, headless=False)
            else:
                # Ya estamos en modo visible; esperar hasta 5 minutos a que el usuario
                # resuelva el captcha y el token aparezca en localStorage.
                logger.warning("Rappi: complete el captcha en el navegador que se abrió (hasta 5 minutos)...")
                try:
                    await page.wait_for_function(
                        "window.localStorage.getItem('access_token') !== null",
                        timeout=300_000)
                except PWTimeout:
                    await page.screenshot(path="/tmp/rappi_login_error.png")
                    await browser.close()
                    raise RuntimeError("Rappi: no se obtuvo access_token tras esperar el captcha")

        token = await page.evaluate("window.localStorage.getItem('access_token')")
        if not token:
            await page.screenshot(path="/tmp/rappi_login_error.png")
            await browser.close()
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
    # La API usa end_date como exclusivo (00:00:00 del día = inicio del día).
    # Se suma 1 día a hasta para que el rango sea inclusivo en ambos extremos.
    end_dt = hasta + timedelta(days=1)

    while True:
        body = {
            "store_ids":  store_ids,
            "start_date": _dh(desde),
            "end_date":   _dh(end_dt),
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

        # fecha (la API devuelve UTC; se convierte a hora local Argentina UTC-3)
        fecha_s = str(items[0].get("created_at", ""))
        fecha   = datetime.now()
        UTC_FMTS = {"%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"}
        for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
            try:
                fecha = datetime.strptime(fecha_s, fmt)
                if fmt in UTC_FMTS:
                    fecha -= timedelta(hours=3)
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


# ── API RECLAMOS — endpoint /defects (una request por store × tipo) ───────────
def api_defects(token, store_id_ar: str, tipo: str,
                desde: datetime, hasta: datetime) -> list[dict]:
    """
    Trae todas las órdenes con defecto del tipo dado para UN solo store_id.
    Pagina automáticamente (size=200) usando total_pages de la respuesta.

    Se hace una request por (store, tipo) para garantizar el mapeo
    store_id → local: el endpoint NO devuelve store_id en cada entry, así que
    lo inyectamos manualmente (`_store_id_num`) junto con el tipo (`_tipo_defecto`)
    para que convertir_reclamos lo use.

    Args:
      token:       bearer access_token de Rappi.
      store_id_ar: ID de tienda CON prefijo "AR" (ej "AR257383").
      tipo:        uno de TIPOS_DEFECTO ("ERROR_MISSING", "ERROR_WRONG", "ERROR_DAMAGED").
      desde, hasta: rango de fechas (datetime).
    """
    all_orders: list[dict] = []
    page = 0
    size = 200
    store_id_num = store_id_ar.replace("AR", "")

    while True:
        body = {
            "country_code": "AR",
            "from":         _d(desde),
            "to":           _d(hasta),
            "order_by":     "DATE",
            "order_id":     "",
            "ordering":     "DESC",
            "page":         page,
            "size":         size,
            "store_ids":    [store_id_ar],
            "type":         tipo,
        }

        try:
            r = requests.post(DEFECTS_URL, headers=_h(token), json=body, timeout=60)
            r.raise_for_status()
            if not r.text.strip():
                logger.warning(f"Rappi defects {store_id_ar}/{tipo} pág {page}: respuesta vacía")
                break
            data = r.json()
        except Exception as e:
            logger.error(f"Rappi defects {store_id_ar}/{tipo} pág {page}: {e}")
            break

        # La API envuelve la respuesta en {"result": {...}}. Si la estructura
        # cambiara en el futuro y mandara los campos en la raíz, también funciona.
        if isinstance(data, dict):
            result = data.get("result") if isinstance(data.get("result"), dict) else data
        else:
            result = {}

        orders = result.get("orders") or []
        if not orders:
            break

        # Inyectar metadata para que convertir_reclamos pueda mapear y traducir
        for o in orders:
            o["_store_id_num"] = store_id_num
            o["_tipo_defecto"] = tipo

        all_orders.extend(orders)

        total_pages = int(result.get("total_pages") or 1)
        if page >= total_pages - 1:
            break
        page += 1

    return all_orders


def traer_defects_todos(token, store_ids_num: list[str],
                        desde: datetime, hasta: datetime) -> list[dict]:
    """
    Loop por store_id × tipo de defecto. Devuelve lista plana de entries
    (con _store_id_num y _tipo_defecto inyectados) lista para convertir.

    store_ids_num: lista de IDs numéricos sin prefijo (los de ALL_RAPPI_IDS).
    """
    all_entries: list[dict] = []
    total_stores = len(store_ids_num)
    total_tipos  = len(TIPOS_DEFECTO)
    total_calls  = total_stores * total_tipos
    hechas       = 0

    for sid_num in store_ids_num:
        sid_str    = str(sid_num).strip()
        store_id_ar = f"AR{sid_str}"
        for tipo in TIPOS_DEFECTO:
            entries = api_defects(token, store_id_ar, tipo, desde, hasta)
            hechas += 1
            if entries:
                # Loguear con la razón en español (INCOMPLETO/EQUIVOCADO/CALIDAD)
                # en lugar del código ERROR_* para que los viewers de logs no
                # marquen estas líneas como errores por simple substring match.
                razon_log = TIPO_A_RAZON.get(tipo, tipo)
                logger.info(
                    f"Rappi defects [{hechas}/{total_calls}] "
                    f"{store_id_ar} {razon_log}: {len(entries)} órdenes")
            all_entries.extend(entries)
            time.sleep(0.25)

    logger.info(
        f"Rappi defects total: {len(all_entries)} órdenes "
        f"({total_stores} stores × {total_tipos} tipos = {total_calls} requests)")
    return all_entries


# ── CONVERTIR reclamos crudos al modelo ───────────────────────────────────────
def convertir_reclamos(entries: list[dict]) -> list[Reclamo]:
    """
    Convierte la lista de entries de /indicators/defects al modelo Reclamo.
    Cada entry trae _store_id_num y _tipo_defecto inyectados por api_defects.

    Campos esperados por entry:
      - order_id (int o str)
      - order_date ("YYYY-MM-DDTHH:MM" — solo fecha útil; hora siempre 00:00)
      - product_name (str con productos separados por coma)
      - comments (texto libre del cliente)
      - reason (código del defecto, ej. "missing_item")  ← se ignora, usamos _tipo_defecto
      - level_1, level_2 (subcategorías técnicas)  ← se ignoran
    """
    reclamos = []

    for o in entries:
        oid = str(o.get("order_id", "")).strip()
        if not oid:
            continue

        sid_num = o.get("_store_id_num", "")
        try:
            tienda = RAPPI_INDEX.get(int(sid_num)) if sid_num else None
        except (TypeError, ValueError):
            tienda = None
        if not tienda:
            logger.warning(f"Rappi reclamo: store_id {sid_num} no encontrado en config (order {oid})")
            continue

        # ── Fecha — el endpoint /defects devuelve solo fecha ("YYYY-MM-DDTHH:MM"),
        #    la hora siempre es 00:00 → no requiere ajuste UTC.
        fecha_s = str(o.get("order_date", "") or "")
        fecha   = datetime.now()
        for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
                    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
            try:
                fecha = datetime.strptime(fecha_s, fmt)
                break
            except ValueError:
                pass
        else:
            logger.warning(f"Rappi reclamo: no se pudo parsear fecha '{fecha_s}' — usando ahora")

        # ── Productos: product_name viene ya como string separado por comas.
        #    Se usa el mismo valor para platos_pedidos y platos_reclamados
        #    porque el endpoint no devuelve el detalle completo de la orden.
        product_name = str(o.get("product_name", "") or "").strip()
        platos       = product_name if product_name else "(sin detalle)"

        # ── Razón: del tipo de defecto del request (más confiable que `reason`,
        #    que viene en código interno tipo "missing_item").
        tipo  = str(o.get("_tipo_defecto", "") or "")
        razon = TIPO_A_RAZON.get(tipo, tipo)

        comentario = str(o.get("comments", "") or "").strip()

        reclamos.append(Reclamo(
            orden_id          = oid,
            app               = "Rappi",
            marca             = tienda["marca"],
            local_id          = tienda["grupo"],
            local_nombre      = tienda["grupo"],
            fecha_orden       = fecha,
            platos_pedidos    = platos,
            platos_reclamados = platos,
            razon             = razon,
            comentario        = comentario,
        ))

    logger.info(f"Rappi reclamos convertidos: {len(reclamos)}")
    return reclamos


# ── FLUJO COMPLETO ────────────────────────────────────────────────────────────
async def extraer_rappi(email, password, fecha_desde, fecha_hasta=None, headless=True):
    """
    Retorna (resenas, reclamos, totales_por_grupo, totales_marca_por_grupo, token).
    - resenas:                 reseñas negativas (1-2 estrellas) con .plato enriquecido
    - reclamos:                órdenes con defecto (missing/wrong/damaged) por local
    - totales_por_grupo:       dict { grupo → total_ordenes }  (vacío: se llena en main)
    - totales_marca_por_grupo: dict { grupo → { marca → total_ordenes } }  (vacío)
    - token:                   access_token para reutilizar en el backfill
    """
    if not fecha_hasta:
        fecha_hasta = datetime.now()

    token = await obtener_token(email, password, headless)

    # 1. Reseñas (con paginación)
    raw     = api_resenas(token, ALL_RAPPI_IDS, fecha_desde, fecha_hasta)
    resenas = convertir(raw)

    # 2. Enriquecer reseñas con nombre real del plato (api_ordenes — una por una).
    #    Ya no se usa api_ordenes para reclamos: el endpoint /defects trae los
    #    productos en product_name, así que solo necesitamos detalle para reseñas.
    order_ids_resenas = [r.orden_id for r in resenas]
    mapa_ordenes: dict[str, dict] = {}
    if order_ids_resenas:
        mapa_ordenes = api_ordenes(token, fecha_desde, fecha_hasta, order_ids_resenas)

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

    # 3. Reclamos — endpoint /indicators/defects (una request por store × tipo)
    logger.info("── Rappi: extrayendo reclamos (defects: missing/wrong/damaged)...")
    entries_defects = traer_defects_todos(token, ALL_RAPPI_IDS, fecha_desde, fecha_hasta)
    reclamos = convertir_reclamos(entries_defects)

    # Los totales de órdenes se obtienen del Google Sheets de pedidos (pedidos_sheets.py).
    # Se retorna también el token para que main.py pueda reutilizarlo en el backfill.
    return resenas, reclamos, {}, {}, token


# ── BACKFILL: reclamos de un día específico ───────────────────────────────────
async def backfill_reclamos_dia(token: str, fecha: datetime) -> list[Reclamo]:
    """
    Descarga los reclamos de Rappi para un día específico usando un token ya obtenido.

    Se usa para rellenar días faltantes en el histórico sin afectar el informe del
    período actual. Los reclamos retornados se guardan solo en el histórico; no se
    incorporan a la lista de reclamos del reporte en curso.

    Parámetros:
      token  — access_token de Rappi (obtenido previamente por extraer_rappi)
      fecha  — cualquier datetime del día a consultar (se normaliza a 00:00 – 23:59)
    """
    dia_desde = fecha.replace(hour=0,  minute=0,  second=0,  microsecond=0)
    dia_hasta = fecha.replace(hour=23, minute=59, second=59, microsecond=0)

    logger.info(f"Rappi backfill: descargando reclamos para {fecha.strftime('%Y-%m-%d')}")

    entries  = traer_defects_todos(token, ALL_RAPPI_IDS, dia_desde, dia_hasta)
    reclamos = convertir_reclamos(entries)

    logger.info(
        f"Rappi backfill {fecha.strftime('%Y-%m-%d')}: {len(reclamos)} reclamos encontrados")
    return reclamos


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
