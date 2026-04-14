"""
Extractor Mercado Libre / Mercado Pago.

El portal usa un Looker Studio de Google que requiere login manual.
El flujo es:
  1. El usuario descarga el CSV del Looker manualmente
  2. Lo coloca en la carpeta configurada (default: ./mercadopago/)
  3. Este módulo lo procesa automáticamente

Columnas del CSV (confirmadas):
  store_name, comment, stars

Limitaciones conocidas del origen de datos:
  - Sin fecha de orden (fecha_orden = None en el modelo Resena)
  - Sin número de orden (se genera uno sintético)
  - Sin nombre de plato (se muestra "(no disponible en ML)")
  - Sin total de órdenes (el denominador del índice viene de otra fuente)
"""
import csv, logging, re
from datetime import datetime
from pathlib import Path

from config.models import Resena
from config.locales import TIENDAS, MP_INDEX

logger = logging.getLogger(__name__)


# ── MATCHING DE NOMBRES DE TIENDA ─────────────────────────────────────────────
# El Looker usa nombres ligeramente distintos a los de la config
# (ej: "Rotesería" vs "Rotisería", "Avalos" vs "Ávalos")
# Usamos matching por similitud en lugar de exacto

def _normalizar_nombre(s: str) -> str:
    """Normaliza para comparación: minúsculas, sin acentos, sin puntuación."""
    import unicodedata
    s = unicodedata.normalize('NFKD', s.lower()).encode('ascii', 'ignore').decode()
    s = re.sub(r'[^a-z0-9 ]', '', s)
    return re.sub(r'\s+', ' ', s).strip()


# Preconstruir índice normalizado de tiendas ML
_ML_INDEX_NORM: dict[str, dict] = {
    _normalizar_nombre(t["mp_nombre"]): t
    for t in TIENDAS
    if t.get("mp_nombre")
}

# También agregar por nombre directo normalizado
for t in TIENDAS:
    key = _normalizar_nombre(t["nombre"])
    if key not in _ML_INDEX_NORM:
        _ML_INDEX_NORM[key] = t


def _buscar_tienda(store_name: str) -> dict | None:
    """
    Busca la tienda por nombre con matching tolerante a errores tipográficos.
    Estrategia: exacto normalizado → contenido parcial → mejor coincidencia.
    """
    norm = _normalizar_nombre(store_name)

    # 1. Match exacto normalizado
    if norm in _ML_INDEX_NORM:
        return _ML_INDEX_NORM[norm]

    # 2. Match parcial: el nombre del CSV está contenido en el nombre de config o viceversa
    for key, tienda in _ML_INDEX_NORM.items():
        if norm in key or key in norm:
            return tienda

    # 3. Match por palabras clave — al menos 2 palabras significativas en común
    palabras_norm = set(norm.split()) - {"de", "la", "el", "las", "los", "y"}
    best_match = None
    best_score = 0
    for key, tienda in _ML_INDEX_NORM.items():
        palabras_key = set(key.split()) - {"de", "la", "el", "las", "los", "y"}
        score = len(palabras_norm & palabras_key)
        if score > best_score and score >= 2:
            best_score = score
            best_match = tienda

    if best_match:
        logger.debug(f"ML: '{store_name}' → '{best_match['nombre']}' (score={best_score})")
        return best_match

    return None


# ── PROCESADOR PRINCIPAL ──────────────────────────────────────────────────────

def parsear_csv_ml(
    ruta_csv: str,
    fecha_desde: datetime,
    fecha_hasta: datetime,
) -> list[Resena]:
    """
    Lee el CSV exportado del Looker de ML y devuelve reseñas de 1-2 estrellas.

    Args:
        ruta_csv:     ruta al archivo CSV descargado del Looker
        fecha_desde:  inicio del período (para el modelo Resena, no usado en ML)
        fecha_hasta:  fin del período (no usado en ML)

    Nota: Mercado Libre no provee fecha en el CSV del Looker.
          Las reseñas se guardan con fecha_orden=None.
    """
    ruta = Path(ruta_csv)
    if not ruta.exists():
        raise FileNotFoundError(f"ML: no se encontró el archivo '{ruta_csv}'")

    logger.info(f"ML: procesando '{ruta.name}' — sin fecha de reseña")

    resenas      = []
    sin_tienda   = []
    total_filas  = 0
    filtradas    = 0

    with open(ruta, encoding="utf-8-sig", errors="replace") as f:
        # detectar delimitador
        muestra = f.read(2048); f.seek(0)
        delim = "," if muestra.count(",") > muestra.count(";") else ";"
        reader = csv.DictReader(f, delimiter=delim)

        for i, row in enumerate(reader, 1):
            total_filas += 1

            # ── estrellas ──
            stars_raw = row.get("stars", row.get("Stars", row.get("calificacion", ""))).strip()
            try:
                estrellas = int(float(stars_raw))
            except (ValueError, TypeError):
                continue

            if estrellas not in (1, 2):
                filtradas += 1
                continue

            # ── tienda ──
            store_name = row.get("store_name", row.get("Store Name", row.get("tienda", ""))).strip()
            tienda = _buscar_tienda(store_name)
            if not tienda:
                sin_tienda.append(store_name)
                logger.warning(f"ML: tienda no encontrada '{store_name}' (fila {i})")
                continue

            # ── comentario ──
            comentario = row.get("comment", row.get("Comment", row.get("comentario", ""))).strip()
            if comentario.lower() in ("nan", "none", ""):
                comentario = ""

            # ── orden sintética (ML no provee número de orden en el Looker) ──
            orden_id = f"ML-{i:04d}"

            resenas.append(Resena(
                orden_id=orden_id,
                app="Mercado Libre",
                marca=tienda["marca"],
                local_id=tienda["grupo"],
                local_nombre=tienda["grupo"],
                fecha_orden=None,   # ML no provee fecha
                estrellas=estrellas,
                plato="(no disponible en ML)",
                tags=[],
                comentario=comentario,
            ))

    logger.info(
        f"ML: {total_filas} filas totales — "
        f"{filtradas} con ≥3 estrellas — "
        f"{len(resenas)} reseñas negativas — "
        f"{len(sin_tienda)} tiendas no encontradas"
    )
    if sin_tienda:
        logger.warning(f"ML: tiendas sin match: {list(set(sin_tienda))}")

    return resenas


# ── BUSCAR CSV MÁS RECIENTE EN CARPETA ───────────────────────────────────────

def encontrar_csv_mas_reciente(carpeta: str = "./mercadopago") -> str | None:
    """
    Busca el CSV más reciente en la carpeta de ML.
    Útil para no tener que especificar el nombre exacto del archivo.
    """
    carpeta_path = Path(carpeta)
    if not carpeta_path.exists():
        return None

    csvs = list(carpeta_path.glob("*.csv")) + list(carpeta_path.glob("*.CSV"))
    if not csvs:
        return None

    # Ordenar por fecha de modificación, más reciente primero
    csvs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(csvs[0])


# ── PROCESADOR DE TOTALES ─────────────────────────────────────────────────────

def parsear_totales_ml(ruta_csv: str) -> dict[str, int]:
    """
    Lee el CSV de totales de órdenes del Looker de ML.
    Columnas esperadas: Store_Name, OrdenesTotales
    Retorna dict { grupo → total_ordenes }.
    Si una tienda aparece duplicada (mismo Store_ID), suma las órdenes.
    """
    import csv as _csv
    ruta = Path(ruta_csv)
    if not ruta.exists():
        raise FileNotFoundError(f"ML totales: no se encontró '{ruta_csv}'")

    totales_por_grupo: dict[str, int] = {}

    with open(ruta, encoding="utf-8-sig", errors="replace") as f:
        muestra = f.read(2048); f.seek(0)
        delim = "," if muestra.count(",") > muestra.count(";") else ";"
        reader = _csv.DictReader(f, delimiter=delim)

        for i, row in enumerate(reader, 1):
            store_name = row.get("Store_Name", row.get("store_name", "")).strip()
            ordenes_raw = row.get("OrdenesTotales", row.get("ordenes_totales", "0")).strip()

            try:
                ordenes = int(str(ordenes_raw).replace(",", "").replace(".", ""))
            except (ValueError, TypeError):
                logger.warning(f"ML totales: no se pudo parsear órdenes '{ordenes_raw}' (fila {i})")
                continue

            tienda = _buscar_tienda(store_name)
            if not tienda:
                logger.warning(f"ML totales: tienda no encontrada '{store_name}' (fila {i})")
                continue

            grupo = tienda["grupo"]
            totales_por_grupo[grupo] = totales_por_grupo.get(grupo, 0) + ordenes

    logger.info(f"ML totales: {len(totales_por_grupo)} grupos, "
                f"{sum(totales_por_grupo.values())} órdenes totales")
    return totales_por_grupo


def encontrar_csv_totales(carpeta: str = "./mercadopago") -> str | None:
    """Busca el CSV de totales más reciente en la carpeta de ML."""
    carpeta_path = Path(carpeta)
    if not carpeta_path.exists():
        return None
    # Buscar archivos que tengan "total" en el nombre primero
    csvs = list(carpeta_path.glob("*total*.csv")) + list(carpeta_path.glob("*Total*.csv"))
    if not csvs:
        # Si no hay uno específico, no lo devolvemos para no confundir con el de reseñas
        return None
    csvs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(csvs[0])
