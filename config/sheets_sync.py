"""
Sincronización con Google Sheets — tres capas de fallback
==========================================================

Cada vez que la aplicación arranca intenta leer la información desde
Google Sheets.  Si la conexión tiene éxito, guarda el resultado en
config/cache_sheets.json.  Si falla (sin internet, Sheets caído, etc.),
usa la última copia guardada.  Si tampoco hay caché (instalación nueva o
archivo borrado), la función devuelve la lista hardcodeada que el
módulo llamador le pasa como parámetro.

Capas (en orden):
  1. Google Sheets  →  si OK, actualiza config/cache_sheets.json
  2. config/cache_sheets.json  (última copia exitosa)
  3. Lista hardcodeada pasada por el llamador

Configuración necesaria en .env:
  SHEETS_ID=<ID del Google Sheet>

  (alternativa: campo "sheets_id" en config_gui.json)

El Google Sheet debe estar publicado como "Cualquier persona con el
enlace puede ver".  Debe tener dos hojas (pestañas):

  Hoja "Tiendas"   — columnas: nombre, marca, grupo, py_id, rappi_id, mp_nombre
  Hoja "Keywords"  — columna:  keyword  (una palabra por fila)

Para obtener el ID: abrir el sheet y copiar la parte de la URL entre
/spreadsheets/d/ y el siguiente /.
  Ejemplo: https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit
  -> sheets_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
"""

import csv
import io
import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

_DIR        = Path(__file__).parent          # config/
_APP_ROOT   = _DIR.parent                    # raiz de la app
_CACHE_PATH = _DIR / "cache_sheets.json"     # copia local de Sheets

# Nombres de las pestanias en el Google Sheet
SHEET_TIENDAS  = "Tiendas"
SHEET_KEYWORDS = "Keywords"

# Timeout de conexion en segundos
_TIMEOUT = 10


# ==============================================================================
# Helpers internos
# ==============================================================================

def _get_csv_url(sheet_name: str) -> str:
    """
    Devuelve la URL CSV para la pestania indicada.
    Lee desde las variables de entorno SHEETS_TIENDAS_URL y SHEETS_KEYWORDS_URL.
    Elimina comillas residuales que dotenv pueda dejar si el valor tiene
    comillas dobles dentro del valor ya entre comillas.
    """
    if sheet_name == SHEET_TIENDAS:
        return os.environ.get("SHEETS_TIENDAS_URL", "").strip().strip('"\'')
    if sheet_name == SHEET_KEYWORDS:
        return os.environ.get("SHEETS_KEYWORDS_URL", "").strip().strip('"\'')
    return ""


def _fetch_csv(sheet_name: str) -> Optional[str]:
    """
    Descarga una pestania del Google Sheet como CSV usando la URL
    configurada en el .env (SHEETS_TIENDAS_URL / SHEETS_KEYWORDS_URL).
    Devuelve el texto CSV o None si la URL no esta configurada o falla.
    """
    url = _get_csv_url(sheet_name)
    if not url:
        log.warning(
            "sheets_sync: no hay URL configurada para '%s'. "
            "Definir SHEETS_TIENDAS_URL y SHEETS_KEYWORDS_URL en el .env",
            sheet_name,
        )
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "resenas-system/1.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read().decode("utf-8")
    except Exception as exc:
        log.warning("sheets_sync: no se pudo descargar '%s' (%s)", sheet_name, exc)
        return None


def _load_cache() -> dict:
    """Carga config/cache_sheets.json. Devuelve {} si no existe o esta corrupto."""
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("sheets_sync: error leyendo cache (%s)", exc)
    return {}


def _save_cache(data: dict) -> None:
    """Persiste data en config/cache_sheets.json con timestamp."""
    try:
        data = dict(data)
        data["ultima_actualizacion"] = datetime.now().isoformat(timespec="seconds")
        _CACHE_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        log.warning("sheets_sync: no se pudo guardar la cache (%s)", exc)


# -- Parsers -------------------------------------------------------------------

def _parse_tiendas(csv_text: str) -> Optional[List[dict]]:
    """
    Convierte el CSV de la hoja Tiendas en una lista de dicts.
    Espera columnas: nombre, marca, grupo, py_id, rappi_id, mp_nombre
    Retorna None si el encabezado no contiene las columnas requeridas.
    """
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        fields = {f.strip().lower() for f in (reader.fieldnames or [])}
        required = {"nombre", "marca", "grupo"}
        if not required.issubset(fields):
            log.warning(
                "sheets_sync: CSV de Tiendas no tiene las columnas requeridas "
                "(encontradas: %s, requeridas: %s)", fields, required
            )
            return None

        tiendas = []
        for row in reader:
            def to_int(v: str) -> Optional[int]:
                v = str(v).strip()
                return int(v) if v.lstrip("-").isdigit() else None

            nombre = row.get("nombre", "").strip()
            if not nombre:
                continue

            tiendas.append({
                "nombre":    nombre,
                "marca":     row.get("marca",     "").strip(),
                "grupo":     row.get("grupo",     "").strip(),
                "py_id":     to_int(row.get("py_id",     "")),
                "rappi_id":  to_int(row.get("rappi_id",  "")),
                "mp_nombre": row.get("mp_nombre", "").strip() or None,
            })

        return tiendas if tiendas else None
    except Exception as exc:
        log.warning("sheets_sync: error parseando CSV de tiendas (%s)", exc)
        return None


def _parse_keywords(csv_text: str) -> Optional[List[str]]:
    """
    Convierte el CSV de la hoja Keywords en una lista de strings.
    Espera una columna llamada 'keyword' (una palabra/raiz por fila).
    Retorna None si el encabezado no es 'keyword' para evitar aceptar
    por error el CSV de otra hoja cuando la pestania no existe.
    """
    try:
        reader = csv.reader(io.StringIO(csv_text))
        header = next(reader, None)
        if not header or header[0].strip().lower() != "keyword":
            log.warning(
                "sheets_sync: CSV de Keywords no tiene 'keyword' como primera columna "
                "(encabezado recibido: %s). Existe la pestania 'Keywords' en el sheet?",
                header
            )
            return None

        keywords = []
        for row in reader:
            if row:
                kw = row[0].strip().lower()
                if kw:
                    keywords.append(kw)
        return sorted(set(keywords)) if keywords else None
    except Exception as exc:
        log.warning("sheets_sync: error parseando CSV de keywords (%s)", exc)
        return None


# ==============================================================================
# API publica
# ==============================================================================

def cargar_tiendas(hardcoded: list) -> List[dict]:
    """
    Devuelve la lista de tiendas usando tres capas de fallback:
      1. Google Sheets  (actualiza la cache si tiene exito)
      2. config/cache_sheets.json
      3. hardcoded      (parametro pasado por el llamador)
    """
    # 1. Google Sheets
    csv_text = _fetch_csv(SHEET_TIENDAS)
    if csv_text:
        tiendas = _parse_tiendas(csv_text)
        if tiendas:
            cache = _load_cache()
            cache["tiendas"] = tiendas
            _save_cache(cache)
            log.info(
                "sheets_sync: tiendas cargadas desde Sheets (%d registros) — cache actualizada",
                len(tiendas),
            )
            return tiendas
        else:
            log.warning(
                "sheets_sync: el CSV de Tiendas llego vacio o sin columnas reconocidas"
            )

    # 2. Cache local
    cache = _load_cache()
    if cache.get("tiendas"):
        ts = cache.get("ultima_actualizacion", "desconocida")
        log.info("sheets_sync: tiendas desde cache local (ultima actualizacion: %s)", ts)
        return cache["tiendas"]

    # 3. Hardcoded
    log.warning(
        "sheets_sync: usando tiendas HARDCODEADAS — "
        "sin conexion a Sheets y sin cache disponible"
    )
    return list(hardcoded)


def cargar_keywords(hardcoded: list) -> List[str]:
    """
    Devuelve la lista de keywords de errores graves usando tres capas de fallback:
      1. Google Sheets  (actualiza la cache si tiene exito)
      2. config/cache_sheets.json
      3. hardcoded      (parametro pasado por el llamador)
    """
    # 1. Google Sheets
    csv_text = _fetch_csv(SHEET_KEYWORDS)
    if csv_text:
        keywords = _parse_keywords(csv_text)
        if keywords:
            cache = _load_cache()
            cache["keywords"] = keywords
            _save_cache(cache)
            log.info(
                "sheets_sync: keywords cargadas desde Sheets (%d palabras) — cache actualizada",
                len(keywords),
            )
            return keywords
        else:
            log.warning(
                "sheets_sync: el CSV de Keywords llego vacio o sin datos reconocibles"
            )

    # 2. Cache local
    cache = _load_cache()
    if cache.get("keywords"):
        ts = cache.get("ultima_actualizacion", "desconocida")
        log.info("sheets_sync: keywords desde cache local (ultima actualizacion: %s)", ts)
        return cache["keywords"]

    # 3. Hardcoded
    log.warning(
        "sheets_sync: usando keywords HARDCODEADAS — "
        "sin conexion a Sheets y sin cache disponible"
    )
    return list(hardcoded)
