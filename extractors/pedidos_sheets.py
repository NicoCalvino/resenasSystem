"""
Extractor de totales de pedidos desde Google Sheets.

En lugar de consultar las APIs de Rappi y PedidosYa para obtener la cantidad
total de pedidos, este módulo descarga el CSV de la tabla de pedidos publicada
en Google Sheets y cuenta cuántos pedidos tuvo cada tienda en el período.

La tabla de pedidos tiene (entre otras) las columnas:
    dateOpen    — fecha/hora de apertura del pedido (YYYY-MM-DD HH:MM:SS)
    marca       — marca de la tienda (ej. "TEA CONNECT", "GREEN EAT")
    tienda      — código de tienda (ej. "PTOPARAR") — equivale a la columna
                  "Codigo" de la tabla de tiendas
    plataforma  — "Rappi", "PedidosYa", etc.

Configuración (.env):
    PEDIDOS_SHEETS_URL  URL CSV del Google Sheets de pedidos
                        (publicado con gid=... &output=csv)

Retorna:
    totales_grupo:           { grupo → total_ordenes }
    totales_marca_por_grupo: { grupo → { marca → total_ordenes } }
    totales_por_plataforma:  { plataforma → { grupo → total_ordenes } }
"""

import csv
import io
import logging
import os
import urllib.request
from datetime import datetime
from typing import Optional

from config.locales import TIENDAS

logger = logging.getLogger(__name__)

_TIMEOUT = 20

# Nombres de columna esperados en el CSV de pedidos (en minúsculas)
_COL_FECHA      = "dateopen"
_COL_MARCA      = "marca"
_COL_TIENDA     = "tienda"
_COL_PLATAFORMA = "plataforma"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalizar(s: str) -> str:
    """Normalización simple para comparación: uppercase sin espacios extremos."""
    return s.strip().upper()


def _parse_fecha(s: str) -> Optional[datetime]:
    """Parsea una fecha en formato 'YYYY-MM-DD HH:MM:SS' (acepta variantes)."""
    s = s.strip()
    if not s:
        return None
    # Tomar solo los primeros 19 caracteres para manejar fracciones de segundo
    s = s[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _build_lookup() -> dict[str, tuple[str, str]]:
    """
    Construye un índice { codigo_normalizado → (grupo, marca_display) }
    a partir de la lista TIENDAS cargada (Sheets > caché > hardcoded).

    Si el campo 'codigo' no está definido en alguna tienda, esa tienda
    simplemente no aparece en el índice y sus pedidos no serán contados
    (se loguea un warning al final indicando cuántas tiendas quedaron fuera).

    El índice se construye por (marca_upper, codigo_upper) para soportar el
    caso en que varias marcas comparten el mismo código de ubicación física
    (ej. "BILGEAAR" para Las Gracias Palermo y Green Eat Billinghurst).
    """
    lookup: dict[tuple[str, str], tuple[str, str]] = {}
    sin_codigo: list[str] = []

    for t in TIENDAS:
        codigo = _normalizar(t.get("codigo") or "")
        marca  = _normalizar(t.get("marca")  or "")
        if not codigo:
            sin_codigo.append(t.get("nombre", "?"))
            continue
        lookup[(marca, codigo)] = (t["grupo"], t["marca"])

    if sin_codigo:
        logger.warning(
            "Pedidos Sheets: %d tiendas sin 'codigo' configurado → sus pedidos "
            "no serán contados. Revisá la columna Codigo en el Google Sheet de "
            "tiendas. Ejemplos: %s",
            len(sin_codigo),
            ", ".join(sin_codigo[:5]) + ("..." if len(sin_codigo) > 5 else ""),
        )

    logger.info("Pedidos Sheets: índice de tiendas construido con %d entradas (marca, codigo).", len(lookup))
    return lookup


# ── Descarga ──────────────────────────────────────────────────────────────────

def _descargar_csv(url: str) -> Optional[str]:
    """Descarga el CSV de pedidos desde la URL dada y retorna el texto crudo."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read()
            # Intentar UTF-8; si falla, latin-1
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1")
    except Exception as exc:
        logger.error("Pedidos Sheets: no se pudo descargar el CSV: %s", exc)
        return None


# ── Función principal ─────────────────────────────────────────────────────────

def calcular_totales_desde_sheets(
    fecha_desde: datetime,
    fecha_hasta: datetime,
) -> tuple[dict[str, int], dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    """
    Descarga el CSV de pedidos (Google Sheets) y cuenta por (grupo, marca)
    dentro del rango [fecha_desde, fecha_hasta].

    Returns:
        totales_grupo           { grupo → total_ordenes }
        totales_marca_por_grupo { grupo → { marca → total_ordenes } }
        totales_por_plataforma  { plataforma → { grupo → total_ordenes } }
    """
    url = os.environ.get("PEDIDOS_SHEETS_URL", "").strip().strip("\"'")
    if not url:
        logger.warning(
            "Pedidos Sheets: variable PEDIDOS_SHEETS_URL no configurada. "
            "Los totales de pedidos no estarán disponibles."
        )
        return {}, {}, {}

    logger.info("Pedidos Sheets: descargando tabla de pedidos...")
    csv_text = _descargar_csv(url)
    if not csv_text:
        return {}, {}, {}

    # Construir índice de tiendas
    lookup = _build_lookup()
    if not lookup:
        logger.error("Pedidos Sheets: el índice de tiendas está vacío. "
                     "¿Tiene la columna 'Codigo' en la hoja Tiendas?")
        return {}, {}, {}

    # Normalizar nombres de columna del CSV
    reader = csv.DictReader(io.StringIO(csv_text))
    raw_fields = reader.fieldnames or []
    # Mapa: nombre_original → nombre_lowercase
    col_map = {f: f.strip().lower() for f in raw_fields}

    # Contadores
    totales_grupo:           dict[str, int]            = {}
    totales_marca_por_grupo: dict[str, dict[str, int]] = {}
    totales_por_plataforma:  dict[str, dict[str, int]] = {}

    contados  = 0
    fuera_de_rango = 0
    sin_match = 0
    sin_fecha = 0

    for row in reader:
        # Normalizar claves del row
        row_norm = {col_map.get(k, k.strip().lower()): v for k, v in row.items()}

        # — Fecha
        fecha_str = row_norm.get(_COL_FECHA, "")
        fecha = _parse_fecha(fecha_str)
        if fecha is None:
            sin_fecha += 1
            continue

        # — Filtro de rango
        if not (fecha_desde <= fecha <= fecha_hasta):
            fuera_de_rango += 1
            continue

        # — Match por (marca, codigo)
        codigo = _normalizar(row_norm.get(_COL_TIENDA, ""))
        marca  = _normalizar(row_norm.get(_COL_MARCA,  ""))
        clave  = (marca, codigo)
        if clave not in lookup:
            sin_match += 1
            continue

        grupo, marca = lookup[clave]

        # — Acumular totales
        totales_grupo[grupo] = totales_grupo.get(grupo, 0) + 1

        if grupo not in totales_marca_por_grupo:
            totales_marca_por_grupo[grupo] = {}
        totales_marca_por_grupo[grupo][marca] = (
            totales_marca_por_grupo[grupo].get(marca, 0) + 1
        )

        # — Por plataforma (para el Excel)
        plataforma = row_norm.get(_COL_PLATAFORMA, "").strip() or "Desconocida"
        if plataforma not in totales_por_plataforma:
            totales_por_plataforma[plataforma] = {}
        totales_por_plataforma[plataforma][grupo] = (
            totales_por_plataforma[plataforma].get(grupo, 0) + 1
        )

        contados += 1

    # — Log resumen
    logger.info(
        "Pedidos Sheets: %d pedidos contados | %d fuera de rango | "
        "%d sin match de código | %d sin fecha",
        contados, fuera_de_rango, sin_match, sin_fecha,
    )
    if sin_match > 0:
        logger.warning(
            "Pedidos Sheets: %d pedidos no pudieron mapearse a ninguna tienda. "
            "Verificá que todos los códigos del CSV de pedidos estén en la "
            "columna 'Codigo' de la hoja Tiendas.",
            sin_match,
        )

    return totales_grupo, totales_marca_por_grupo, totales_por_plataforma
