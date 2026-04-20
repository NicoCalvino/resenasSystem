"""
Configuración de tiendas extraída de la hoja Referencias del Excel.
Marcas reales: Las Gracias, Tea Connection, Green Eat.
Grupos = locales físicos (Billinghurst, Ávalos, Cabildo, etc.)

Estructura:
  - py_id:     ID numérico en PedidosYa
  - rappi_id:  ID numérico en Rappi
  - mp_nombre: Nombre en Mercado Pago (para matching)
  - grupo:     Local físico al que pertenece (usado para agrupar el informe)
  - marca:     Marca de la cadena

Fuente de datos (orden de prioridad):
  1. Ruta compartida configurada en config_gui.json  →  "tiendas_path"
  2. config/tiendas.json  (copia local)
  3. Lista _TIENDAS_HARDCODED al final de este archivo  (fallback de emergencia)
"""
import json as _json
from pathlib import Path as _Path

_LOCALES_DIR = _Path(__file__).parent
_APP_ROOT    = _LOCALES_DIR.parent


def _leer_tiendas() -> list:
    """
    Carga la lista de tiendas desde JSON (compartido o local).
    Si no hay JSON disponible, devuelve el fallback hardcodeado.
    """
    # ── 1. Ruta compartida configurada en config_gui.json ─────────────────────
    cfg_path = _APP_ROOT / "config_gui.json"
    if cfg_path.exists():
        try:
            cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
            shared = cfg.get("tiendas_path", "").strip()
            if shared:
                p = _Path(shared)
                if p.exists():
                    return _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass

    # ── 2. tiendas.json local (config/tiendas.json) ───────────────────────────
    local_json = _LOCALES_DIR / "tiendas.json"
    if local_json.exists():
        try:
            return _json.loads(local_json.read_text(encoding="utf-8"))
        except Exception:
            pass

    # ── 3. Fallback hardcodeado ───────────────────────────────────────────────
    return list(_TIENDAS_HARDCODED)


# ── Lista hardcodeada (fallback de emergencia) ────────────────────────────────
_TIENDAS_HARDCODED = [
    # ── Las Gracias ──────────────────────────────────────────────────────────
    {"nombre": "Las Gracias Rotisería Belgrano",     "marca": "Las Gracias", "grupo": "Cabildo",           "py_id": 595347, "rappi_id": 257383, "mp_nombre": "Las Gracias Rotisería Belgrano"},
    {"nombre": "Las Gracias Rotisería Palermo",      "marca": "Las Gracias", "grupo": "Billinghurst",      "py_id": 595409, "rappi_id": 257378, "mp_nombre": "Las Gracias Rotisería Palermo"},
    {"nombre": "Las Gracias Rotisería Recoleta",     "marca": "Las Gracias", "grupo": "Santa Fe",          "py_id": 595511, "rappi_id": 257382, "mp_nombre": "Las Gracias Rotisería Recoleta"},
    {"nombre": "Las Gracias Rotisería Caballito",    "marca": "Las Gracias", "grupo": "Formosa",           "py_id": 595293, "rappi_id": 257366, "mp_nombre": "Las Gracias Rotesería Caballito"},
    {"nombre": "Las Gracias Rotisería Villa Urquiza","marca": "Las Gracias", "grupo": "Ávalos",            "py_id": 595376, "rappi_id": 257377, "mp_nombre": "Las Gracias Rotisería Villa Urquiza"},
    {"nombre": "Las Gracias Rotisería Devoto",       "marca": "Las Gracias", "grupo": "Asunción",          "py_id": 595226, "rappi_id": 257380, "mp_nombre": "Las Gracias Rotisería Devoto"},
    {"nombre": "Las Gracias Rotisería Martinez",     "marca": "Las Gracias", "grupo": "Martinez",          "py_id": 595268, "rappi_id": 257381, "mp_nombre": "Las Gracias Rotisería Martinez"},

    # ── Tea Connection (locales con PedidosYa + Rappi) ───────────────────────
    {"nombre": "Tea Connection Dot",                  "marca": "Tea Connection", "grupo": "DOT",               "py_id": 507619,  "rappi_id": 226171, "mp_nombre": "Tea Connection Dot"},
    {"nombre": "Tea Connection Puerto Madero",        "marca": "Tea Connection", "grupo": "Puerto Madero",     "py_id": 545208,  "rappi_id": 237996, "mp_nombre": None},
    {"nombre": "Tea Connection Gorostiaga",           "marca": "Tea Connection", "grupo": "Gorostiaga",        "py_id": 119043,  "rappi_id": 111094, "mp_nombre": "Tea Connection Gorostiaga"},
    {"nombre": "Tea Connection Flores",               "marca": "Tea Connection", "grupo": "Flores",            "py_id": 542867,  "rappi_id": 238005, "mp_nombre": None},
    {"nombre": "Tea Connection Villa Luro",           "marca": "Tea Connection", "grupo": "Villa Luro",        "py_id": 546270,  "rappi_id": 238481, "mp_nombre": None},
    {"nombre": "Tea Connection Scalabrini",           "marca": "Tea Connection", "grupo": "Scalabrini",        "py_id": 135030,  "rappi_id": 125382, "mp_nombre": "Tea Connection Scalabrini"},
    {"nombre": "Tea Connection Abasto",               "marca": "Tea Connection", "grupo": "Abasto",            "py_id": 161520,  "rappi_id": 129921, "mp_nombre": "Tea Connection Abasto"},
    {"nombre": "Tea Connection Uriburu",              "marca": "Tea Connection", "grupo": "Uriburu",           "py_id": 160447,  "rappi_id": 111294, "mp_nombre": "Tea Connection Uriburu"},
    {"nombre": "Tea Connection Conde",                "marca": "Tea Connection", "grupo": "Conde",             "py_id": 119044,  "rappi_id": 115782, "mp_nombre": "Tea Connection Conde"},
    {"nombre": "Tea Connection Montevideo",           "marca": "Tea Connection", "grupo": "Montevideo",        "py_id": 223,     "rappi_id": 114239, "mp_nombre": "Tea Connection Montevideo"},
    {"nombre": "Tea Connection Vuelta De Obligado",   "marca": "Tea Connection", "grupo": "Vuelta de Obligado","py_id": 320846,  "rappi_id": 117038, "mp_nombre": "Tea Connection Belgrano"},
    {"nombre": "Tea Connection Sinclair",             "marca": "Tea Connection", "grupo": "Sinclair",          "py_id": 119042,  "rappi_id": 111105, "mp_nombre": "Tea Connection Sinclair"},
    {"nombre": "Tea Connection Ávalos",               "marca": "Tea Connection", "grupo": "Ávalos",            "py_id": 119045,  "rappi_id": 111876, "mp_nombre": "Tea Connection Avalos"},
    {"nombre": "Tea Connection Libertador",           "marca": "Tea Connection", "grupo": "Libertador",        "py_id": 129017,  "rappi_id": 122879, "mp_nombre": "Tea Connection Libertador"},
    {"nombre": "Tea Connection Asunción",             "marca": "Tea Connection", "grupo": "Asunción",          "py_id": 254907,  "rappi_id": 151640, "mp_nombre": "Tea Connection Asunción"},
    {"nombre": "Tea Connection Formosa",              "marca": "Tea Connection", "grupo": "Formosa",           "py_id": 119041,  "rappi_id": 111875, "mp_nombre": "Tea Connection Formosa"},
    {"nombre": "Tea Connection Lacroze",              "marca": "Tea Connection", "grupo": "Lacroze",           "py_id": 226,     "rappi_id": 116438, "mp_nombre": "Tea Connection Lacroze"},

    # ── Tea Connection Turbo (solo Rappi, sin PedidosYa) ─────────────────────
    {"nombre": "Tea Connection Turbo Gorostiaga",     "marca": "Tea Connection", "grupo": "Gorostiaga",        "py_id": None,    "rappi_id": 226155, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Uriburu",        "marca": "Tea Connection", "grupo": "Uriburu",           "py_id": None,    "rappi_id": 224951, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Conde",          "marca": "Tea Connection", "grupo": "Conde",             "py_id": None,    "rappi_id": 224957, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Libertador",     "marca": "Tea Connection", "grupo": "Libertador",        "py_id": None,    "rappi_id": 225113, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Vuelta de Obligado","marca": "Tea Connection","grupo": "Vuelta de Obligado","py_id": None,   "rappi_id": 226210, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Scalabrini",     "marca": "Tea Connection", "grupo": "Scalabrini",        "py_id": None,    "rappi_id": 223109, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Formosa",        "marca": "Tea Connection", "grupo": "Formosa",           "py_id": None,    "rappi_id": 222963, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Ávalos",         "marca": "Tea Connection", "grupo": "Ávalos",            "py_id": None,    "rappi_id": 226214, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Lacroze",        "marca": "Tea Connection", "grupo": "Lacroze",           "py_id": None,    "rappi_id": 222964, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Montevideo",     "marca": "Tea Connection", "grupo": "Montevideo",        "py_id": None,    "rappi_id": 222969, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Sinclair",       "marca": "Tea Connection", "grupo": "Sinclair",          "py_id": None,    "rappi_id": 223014, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Abasto",         "marca": "Tea Connection", "grupo": "Abasto",            "py_id": None,    "rappi_id": 227169, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Pueyrredón",     "marca": "Tea Connection", "grupo": "Pueyrredon",        "py_id": None,    "rappi_id": 228145, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Asunción",       "marca": "Tea Connection", "grupo": "Asunción",          "py_id": None,    "rappi_id": 226204, "mp_nombre": None},
    {"nombre": "Tea Connection Turbo Dot",            "marca": "Tea Connection", "grupo": "DOT",               "py_id": None,    "rappi_id": 227955, "mp_nombre": None},

    # ── Green Eat (locales con PedidosYa + Rappi) ────────────────────────────
    {"nombre": "Green Eat Abasto",     "marca": "Green Eat", "grupo": "Abasto",      "py_id": 54149,  "rappi_id": 117698, "mp_nombre": "Green Eat Abasto"},
    {"nombre": "Green Eat Florida",    "marca": "Green Eat", "grupo": "Florida",     "py_id": 195164, "rappi_id": 237979, "mp_nombre": "Green Eat Florida"},
    {"nombre": "Green Eat Santa Fe",   "marca": "Green Eat", "grupo": "Santa Fe",    "py_id": 54151,  "rappi_id": 121087, "mp_nombre": "Green Eat Santa Fe"},
    {"nombre": "Green Eat Ávalos",     "marca": "Green Eat", "grupo": "Ávalos",      "py_id": 506530, "rappi_id": 127690, "mp_nombre": "Green Eat Avalos"},
    {"nombre": "Green Eat Asunción",   "marca": "Green Eat", "grupo": "Asunción",    "py_id": 251110, "rappi_id": 151636, "mp_nombre": "Green Eat Asunción"},
    {"nombre": "Green Eat Cabildo",    "marca": "Green Eat", "grupo": "Cabildo",     "py_id": 64082,  "rappi_id": 117696, "mp_nombre": "Green Eat Cabildo"},
    {"nombre": "Green Eat Rivadavia",  "marca": "Green Eat", "grupo": "Rivadavia",   "py_id": 54153,  "rappi_id": 117699, "mp_nombre": "Green Eat Rivadavia"},
    {"nombre": "Green Eat Billinghurst","marca":"Green Eat", "grupo": "Billinghurst","py_id": 54150,  "rappi_id": 117697, "mp_nombre": "Green Eat Billinghurst"},
    {"nombre": "Green Eat Dot",        "marca": "Green Eat", "grupo": "DOT",         "py_id": 315467, "rappi_id": 117700, "mp_nombre": "Green Eat Dot"},
    {"nombre": "Green Eat Sinclair",   "marca": "Green Eat", "grupo": "Sinclair",    "py_id": 253624, "rappi_id": 151528, "mp_nombre": "Green Eat Sinclair"},
    {"nombre": "Green Eat Flores",     "marca": "Green Eat", "grupo": "Flores",      "py_id": 542865, "rappi_id": 237979, "mp_nombre": None},
    {"nombre": "Green Eat Villa Luro", "marca": "Green Eat", "grupo": "Villa Luro",  "py_id": 546437, "rappi_id": 238477, "mp_nombre": None},
    {"nombre": "Green Eat Libertador", "marca": "Green Eat", "grupo": "Libertador",  "py_id": 149209, "rappi_id": 127651, "mp_nombre": "Green Eat Libertador"},
    {"nombre": "Green Eat Pueyrredón", "marca": "Green Eat", "grupo": "Pueyrredon",  "py_id": None,   "rappi_id": None,   "mp_nombre": "Green Eat Pueyrredon"},

    # ── Green Eat Turbo (solo Rappi) ─────────────────────────────────────────
    {"nombre": "Green Eat Turbo Asunción",    "marca": "Green Eat", "grupo": "Asunción",    "py_id": None, "rappi_id": 226207, "mp_nombre": None},
    {"nombre": "Green Eat Turbo Sinclair",    "marca": "Green Eat", "grupo": "Sinclair",    "py_id": None, "rappi_id": 225112, "mp_nombre": None},
    {"nombre": "Green Eat Turbo Ávalos",      "marca": "Green Eat", "grupo": "Ávalos",      "py_id": None, "rappi_id": 226213, "mp_nombre": None},
    {"nombre": "Green Eat Turbo Cabildo",     "marca": "Green Eat", "grupo": "Cabildo",     "py_id": None, "rappi_id": 219350, "mp_nombre": None},
    {"nombre": "Green Eat Turbo Florida",     "marca": "Green Eat", "grupo": "Florida",     "py_id": None, "rappi_id": 220481, "mp_nombre": None},
    {"nombre": "Green Eat Turbo Abasto",      "marca": "Green Eat", "grupo": "Abasto",      "py_id": None, "rappi_id": 221084, "mp_nombre": None},
    {"nombre": "Green Eat Turbo Libertador",  "marca": "Green Eat", "grupo": "Libertador",  "py_id": None, "rappi_id": 226206, "mp_nombre": None},
    {"nombre": "Green Eat Turbo Pueyrredón",  "marca": "Green Eat", "grupo": "Pueyrredon",  "py_id": None, "rappi_id": 226607, "mp_nombre": None},
    {"nombre": "Green Eat Turbo Rivadavia",   "marca": "Green Eat", "grupo": "Rivadavia",   "py_id": None, "rappi_id": 219368, "mp_nombre": None},
    {"nombre": "Green Eat Turbo Santa Fe",    "marca": "Green Eat", "grupo": "Santa Fe",    "py_id": None, "rappi_id": 220813, "mp_nombre": None},
    {"nombre": "Green Eat Turbo Billinghurst","marca": "Green Eat", "grupo": "Billinghurst","py_id": None, "rappi_id": 216559, "mp_nombre": None},
    {"nombre": "Green Eat Turbo Dot",         "marca": "Green Eat", "grupo": "DOT",         "py_id": None, "rappi_id": 228142, "mp_nombre": None},
]

# ── Cargar tiendas (JSON compartido > JSON local > hardcoded) ─────────────────
TIENDAS = _leer_tiendas()

# ── Índices de acceso rápido ──────────────────────────────────────────────────

# por rappi_id → tienda
RAPPI_INDEX = {t["rappi_id"]: t for t in TIENDAS if t["rappi_id"]}

# por py_id → tienda
PY_INDEX = {t["py_id"]: t for t in TIENDAS if t["py_id"]}

# por mp_nombre → tienda
MP_INDEX = {t["mp_nombre"]: t for t in TIENDAS if t["mp_nombre"]}

# todos los rappi_ids como lista de strings (formato que usa la API)
ALL_RAPPI_IDS = [str(t["rappi_id"]) for t in TIENDAS if t["rappi_id"]]
ALL_RAPPI_IDS_AR = [f"AR{t['rappi_id']}" for t in TIENDAS if t["rappi_id"]]


# todos los py_ids como lista de strings
ALL_PY_IDS = [str(t["py_id"]) for t in TIENDAS if t["py_id"]]

# grupos únicos (locales físicos)
GRUPOS = sorted(set(t["grupo"] for t in TIENDAS))

# ── Keywords de errores graves (extraídos de la hoja Referencias) ─────────────
# Son prefijos/raíces — se usan con búsqueda de subcadena (no word boundary)
# Se pueden editar desde la GUI; se persisten en config/keywords_graves.json.
_KEYWORDS_GRAVES_HARDCODED = [
    "agria", "agrio", "alambre", "asco", "asqueros", "astilla", "babos",
    "bicho", "cabello", "carbón", "carbon", "carbonizad", "clip", "cristal",
    "crud", "cucaracha", "descomp", "diarrea", "elástico", "elastico",
    "enferm", "fétid", "fetid", "grampa", "grapa", "gusano", "hilo",
    "hongo", "hormiga", "hospital", "intoxica", "larva", "madera", "médico",
    "medico", "metal", "moho", "mosca", "pelo", "piedra", "piedrita",
    "plástico", "plastico", "podrid", "quemad", "ranci", "sangr", "soga",
    "sucia", "suciedad", "sucio", "unia", "vidrio", "vomit",
]


def _leer_keywords_graves() -> list:
    """
    Carga la lista de keywords graves desde config/keywords_graves.json.
    Si el archivo no existe o está corrupto, devuelve la lista hardcodeada.
    """
    keywords_path = _LOCALES_DIR / "keywords_graves.json"
    if keywords_path.exists():
        try:
            data = _json.loads(keywords_path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return sorted(set(str(k).strip().lower() for k in data if str(k).strip()))
        except Exception:
            pass
    return list(_KEYWORDS_GRAVES_HARDCODED)


KEYWORDS_GRAVES = _leer_keywords_graves()
