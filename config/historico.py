"""
historico.py — Acumulado de reclamos en un archivo JSON compartido.

Lee y escribe un archivo JSON ubicado en Google Drive (o cualquier ruta
accesible). La ruta se detecta automáticamente buscando la carpeta
"Unidades compartidas\\informes\\Referencias" en todas las unidades del
sistema, lo que cubre Google Drive for Desktop en cualquier letra de unidad.

Si se prefiere una ruta explícita, se puede definir en .env:
  HISTORICO_JSON_PATH=H:\\Mi unidad\\informes\\Referencias\\historico.json

Estructura del JSON:
  {
    "reclamos": [
      {
        "fecha":          "2026-05-09",
        "tienda":         "Las Gracias - Billinghurst",
        "plataforma":     "Rappi",
        "orden_id":       "123456",
        "motivo":         "INCOMPLETA",
        "es_error_grave": "SI"
      },
      ...
    ]
  }

Deduplicación:
  Clave (plataforma, orden_id): si ya existe, el reclamo se omite.

Concurrencia:
  Se usa un archivo .lock junto al JSON para evitar escrituras simultáneas
  cuando dos usuarios ejecutan el script al mismo tiempo.
"""

import json
import logging
import os
import string
import time
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

_LOCK_TIMEOUT_SEG = 30   # espera máxima para obtener el lock
_LOCK_RETRY_SEG   = 0.5  # intervalo entre reintentos

# Subcarpeta fija dentro del drive compartido donde vive el historico
_SUBCARPETA = Path("informes") / "Referencias" / "historico.json"

# Nombres posibles de la carpeta de unidades compartidas según idioma del sistema
_NOMBRES_COMPARTIDAS = ["Unidades compartidas", "Shared drives"]


# ==============================================================================
# Detección automática de Google Drive
# ==============================================================================

def _detectar_ruta_drive() -> Path | None:
    """
    Busca Google Drive for Desktop escaneando todas las letras de unidad
    del sistema (C-Z) y buscando la carpeta de Unidades compartidas.
    Dentro de cada unidad compartida busca la subcarpeta
    'informes\\Referencias' donde vive el historico.json.
    Devuelve la ruta completa al historico.json si la encuentra, o None.
    """
    for letra in string.ascii_uppercase:
        raiz = Path(f"{letra}:\\")
        if not raiz.exists():
            continue
        for nombre_compartidas in _NOMBRES_COMPARTIDAS:
            carpeta_compartidas = raiz / nombre_compartidas
            if not carpeta_compartidas.is_dir():
                continue

            # Caso A: la subcarpeta informes\Referencias está directamente
            # dentro de "Unidades compartidas" (sin carpeta intermedia)
            candidato = carpeta_compartidas / _SUBCARPETA
            if candidato.parent.exists():
                log.info("historico: Drive compartido detectado en %s", carpeta_compartidas)
                return candidato

            # Caso B: hay una carpeta intermedia con el nombre del drive compartido
            try:
                subdirs = [d for d in carpeta_compartidas.iterdir() if d.is_dir()]
            except PermissionError:
                continue
            for unidad_compartida in subdirs:
                candidato = unidad_compartida / _SUBCARPETA
                if candidato.parent.exists():
                    log.info("historico: Drive compartido detectado en %s", unidad_compartida)
                    return candidato
    return None


def _obtener_ruta_json() -> Path | None:
    """
    Determina la ruta al JSON con el siguiente orden de prioridad:
      1. Variable de entorno HISTORICO_JSON_PATH (explícita)
      2. Detección automática de Google Drive for Desktop
    """
    # 1. Variable de entorno explícita
    ruta_str = os.environ.get("HISTORICO_JSON_PATH", "").strip().strip("\"'")
    if ruta_str:
        return Path(ruta_str)

    # 2. Auto-detección
    ruta = _detectar_ruta_drive()
    if ruta:
        return ruta

    log.warning(
        "historico: no se encontró Google Drive y HISTORICO_JSON_PATH no está "
        "configurado — omitiendo registro histórico"
    )
    return None


# ==============================================================================
# Helpers internos
# ==============================================================================

def _normalizar_motivo(razon: str) -> str:
    """Normaliza la razón del reclamo a INCOMPLETA / EQUIVOCADA / CALIDAD."""
    r = razon.strip().upper().split("|")[0].strip()
    if any(k in r for k in ("INCOMPLETO", "INCOMPLETA", "MISSING")):
        return "INCOMPLETA"
    if any(k in r for k in ("EQUIVOCADO", "EQUIVOCADA", "WRONG", "DIFFERENCE", "DISTINTO")):
        return "EQUIVOCADA"
    if any(k in r for k in ("CALIDAD", "QUALITY", "POOR")):
        return "CALIDAD"
    return r or "(sin motivo)"


def _nombre_tienda(marca: str, local_nombre: str) -> str:
    """Construye el nombre de tienda combinando marca y local."""
    if marca and local_nombre and marca.strip() != local_nombre.strip():
        return f"{marca.strip()} - {local_nombre.strip()}"
    return (marca or local_nombre or "").strip()


def _leer_json(ruta: Path) -> dict:
    """Lee el JSON existente o devuelve estructura vacía si no existe."""
    if ruta.exists():
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("historico: no se pudo leer %s (%s) — se inicia desde cero", ruta, e)
    return {"reclamos": []}


def _escribir_json(ruta: Path, data: dict) -> None:
    """Escribe el JSON de forma atómica (temp file + rename)."""
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ruta)


class _FileLock:
    """
    Lock de archivo simple usando un .lock junto al JSON.
    Crea el archivo de lock al entrar y lo elimina al salir.
    Si el lock lleva más de _LOCK_TIMEOUT_SEG segundos, se considera
    abandonado y se toma de todas formas.
    """

    def __init__(self, ruta_json: Path):
        self._lock_path = ruta_json.with_suffix(".lock")

    def __enter__(self):
        inicio = time.time()
        while True:
            try:
                # O_CREAT | O_EXCL → falla si ya existe (operación atómica)
                fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                # Lock en uso — verificar si es muy viejo (proceso muerto)
                try:
                    edad = time.time() - self._lock_path.stat().st_mtime
                    if edad > _LOCK_TIMEOUT_SEG:
                        log.warning("historico: lock abandonado (%.0f s), tomando control", edad)
                        self._lock_path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue  # otro proceso lo eliminó justo ahora
                if time.time() - inicio > _LOCK_TIMEOUT_SEG:
                    raise TimeoutError(
                        f"No se pudo obtener el lock en {_LOCK_TIMEOUT_SEG}s: {self._lock_path}"
                    )
                time.sleep(_LOCK_RETRY_SEG)

    def __exit__(self, *_):
        self._lock_path.unlink(missing_ok=True)


# ==============================================================================
# API pública
# ==============================================================================

def leer_historico() -> dict:
    """
    Lee y devuelve el contenido del historico.json.
    Retorna {"reclamos": []} si no se encuentra o está vacío.
    """
    ruta = _obtener_ruta_json()
    if ruta is None:
        log.warning("historico.leer_historico: no se encontró ruta al JSON")
        return {"reclamos": []}
    data = _leer_json(ruta)
    log.info(
        "historico.leer_historico: %d reclamos cargados desde %s",
        len(data.get("reclamos", [])),
        ruta,
    )
    return data


def registrar_ejecucion(
    reclamos: list,
    fecha_ejecucion: datetime,
) -> None:
    """
    Registra los reclamos de una ejecución en el JSON compartido.

    Parámetros:
      reclamos        — lista de objetos Reclamo
      fecha_ejecucion — datetime de referencia (normalmente fecha_hasta),
                        usado como fecha de fallback si el reclamo no tiene
                        fecha propia
    """
    ruta = _obtener_ruta_json()
    if ruta is None:
        return

    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning("historico: no se pudo crear la carpeta %s: %s", ruta.parent, e)
        return

    fecha_str = fecha_ejecucion.strftime("%Y-%m-%d")

    from processor.procesador import es_error_grave

    try:
        with _FileLock(ruta):
            data = _leer_json(ruta)

            # Asegurar que la clave existe (compatibilidad con JSONs viejos)
            data.setdefault("reclamos", [])

            # Índice de claves ya existentes para deduplicar
            existentes: set[tuple] = {
                (r["plataforma"], r["orden_id"])
                for r in data["reclamos"]
            }

            nuevos = 0
            for rc in reclamos:
                clave = (rc.app, rc.orden_id)
                if clave in existentes:
                    continue

                tienda = _nombre_tienda(rc.marca, rc.local_nombre)
                motivo = _normalizar_motivo(rc.razon or "")
                grave  = es_error_grave(rc.comentario or "", [rc.razon or ""])
                fecha_orden = (
                    rc.fecha_orden.strftime("%Y-%m-%d")
                    if rc.fecha_orden else fecha_str
                )

                data["reclamos"].append({
                    "fecha":          fecha_orden,
                    "tienda":         tienda,
                    "plataforma":     rc.app,
                    "orden_id":       rc.orden_id,
                    "motivo":         motivo,
                    "es_error_grave": "SI" if grave else "NO",
                })
                existentes.add(clave)
                nuevos += 1

            omitidos = len(reclamos) - nuevos
            if nuevos:
                log.info("historico: %d reclamos nuevos registrados (%d ya existían)", nuevos, omitidos)
            else:
                log.info("historico: todos los reclamos ya estaban registrados (%d omitidos)", omitidos)

            _escribir_json(ruta, data)
            log.info("historico: guardado en %s", ruta)

    except TimeoutError as e:
        log.error("historico: %s", e)
    except Exception as e:
        log.error("historico: error inesperado: %s", e)


# ==============================================================================
# Verificación de días por plataforma (backfill del histórico)
# ==============================================================================

# Tabla de normalización de nombres de plataforma → slug usado como clave en el JSON.
# La clave en el JSON es: "dias_verificados_{slug}"
_SLUG_PLATAFORMA: dict[str, str] = {
    "rappi":         "rappi",
    "pedidosya":     "pedidosya",
    "peya":          "pedidosya",
    "mercadolibre":  "ml",
    "mercado libre": "ml",
    "mercado_libre": "ml",
    "ml":            "ml",
}


def _slug_plat(plataforma: str) -> str:
    """Convierte un nombre de plataforma a su slug normalizado."""
    key = plataforma.strip().lower().replace(" ", "_")
    return _SLUG_PLATAFORMA.get(key, key)


def obtener_dias_no_verificados(
    plataforma: str,
    fecha_desde: datetime,
    fecha_hasta: datetime,
) -> list[str]:
    """
    Devuelve las fechas (YYYY-MM-DD) en el rango [fecha_desde, fecha_hasta]
    que requieren ser (re-)consultadas para la plataforma indicada.

    Una fecha entra al resultado si cumple cualquiera de:
      1. NO está marcada como verificada (nunca se consultó la fuente).
      2. SÍ está marcada como verificada PERO no tiene ningún reclamo
         registrado para esa plataforma/fecha en el histórico — esto cubre
         el caso de plataformas que tardan 24-72 h en exponer reclamos
         recientes: un día que se consultó "vacío" se vuelve a revisar por
         si aparecieron reclamos después.

    Plataformas reconocidas: "rappi", "pedidosya" / "peya", "ml" / "mercado libre".
    Retorna lista vacía si no se puede acceder al histórico.
    """
    ruta = _obtener_ruta_json()
    if ruta is None:
        return []

    slug  = _slug_plat(plataforma)
    clave = f"dias_verificados_{slug}"
    data  = _leer_json(ruta)
    verificados = set(data.get(clave, []))

    # Set de fechas (YYYY-MM-DD) que ya tienen al menos un reclamo registrado
    # para esta plataforma. Se compara por slug para tolerar variaciones de
    # capitalización / espacios en el campo "plataforma" del JSON.
    fechas_con_reclamos: set[str] = {
        r.get("fecha", "")
        for r in data.get("reclamos", [])
        if _slug_plat(r.get("plataforma", "")) == slug and r.get("fecha")
    }

    resultado: list[str] = []
    current = fecha_desde.date()
    hasta   = fecha_hasta.date()
    while current <= hasta:
        fecha_str = current.strftime("%Y-%m-%d")
        if fecha_str not in verificados:
            resultado.append(fecha_str)
        elif fecha_str not in fechas_con_reclamos:
            # Día marcado verificado pero sin reclamos registrados — se
            # re-revisa por si aparecieron reclamos después de la primera
            # consulta.
            resultado.append(fecha_str)
        current += timedelta(days=1)

    log.info(
        "historico: %d días a (re-)verificar %s en rango %s → %s",
        len(resultado), plataforma, fecha_desde.date(), fecha_hasta.date(),
    )
    return resultado


def marcar_dias_verificados(plataforma: str, fechas: list[str]) -> None:
    """
    Marca las fechas dadas (YYYY-MM-DD) como verificadas para la plataforma
    indicada en el histórico.

    Se llama tanto cuando se descargaron reclamos como cuando el día no tuvo
    ninguno, para evitar re-consultar en ejecuciones futuras.
    No hace nada si no se puede acceder al histórico o si la lista está vacía.
    """
    if not fechas:
        return

    ruta = _obtener_ruta_json()
    if ruta is None:
        return

    slug  = _slug_plat(plataforma)
    clave = f"dias_verificados_{slug}"

    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with _FileLock(ruta):
            data = _leer_json(ruta)
            data.setdefault(clave, [])
            existentes = set(data[clave])
            nuevos = 0
            for f in fechas:
                if f not in existentes:
                    data[clave].append(f)
                    existentes.add(f)
                    nuevos += 1
            if nuevos:
                data[clave].sort()
                _escribir_json(ruta, data)
                log.info("historico: %d días %s marcados como verificados", nuevos, plataforma)
            else:
                log.debug(
                    "historico: todos los días %s indicados ya estaban verificados", plataforma)
    except TimeoutError as e:
        log.error("historico: timeout marcando días verificados (%s): %s", plataforma, e)
    except Exception as e:
        log.error("historico: error marcando días verificados (%s): %s", plataforma, e)


# ── Wrappers backward-compat (Rappi) ─────────────────────────────────────────

def obtener_dias_no_verificados_rappi(fecha_desde: datetime, fecha_hasta: datetime) -> list[str]:
    """Alias de obtener_dias_no_verificados('rappi', ...)."""
    return obtener_dias_no_verificados("rappi", fecha_desde, fecha_hasta)


def marcar_dias_verificados_rappi(fechas: list[str]) -> None:
    """Alias de marcar_dias_verificados('rappi', ...)."""
    marcar_dias_verificados("rappi", fechas)
