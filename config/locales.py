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
  - codigo:    Código de tienda en la tabla de pedidos de Google Sheets
               (columna "Codigo" de la hoja Tiendas; se usa para contar totales)

Fuente de datos (orden de prioridad):
  1. Google Sheets  (pestaña "Tiendas" / "Keywords")  →  actualiza caché si funciona
  2. config/cache_sheets.json  (última descarga exitosa de Sheets)
  3. Lista _TIENDAS_HARDCODED / _KEYWORDS_GRAVES_HARDCODED  (emergencia)

Para activar Sheets: agregar "sheets_id": "<ID del sheet>" en config_gui.json.
Ver config/sheets_sync.py para instrucciones detalladas.
"""
import json as _json
from pathlib import Path as _Path

from config.sheets_sync import cargar_tiendas as _cargar_tiendas
from config.sheets_sync import cargar_keywords as _cargar_keywords

_LOCALES_DIR = _Path(__file__).parent
_APP_ROOT    = _LOCALES_DIR.parent


# ── Lista hardcodeada (fallback de emergencia) ────────────────────────────────
_TIENDAS_HARDCODED = [
    # ── Las Gracias ──────────────────────────────────────────────────────────
    {"nombre": "Las Gracias Rotisería Belgrano",     "marca": "Las Gracias", "grupo": "Cabildo",           "py_id": 595347, "rappi_id": 257383, "mp_nombre": "Las Gracias Rotisería Belgrano",    "dk": False, "codigo": None},
    {"nombre": "Las Gracias Rotisería Palermo",      "marca": "Las Gracias", "grupo": "Billinghurst",      "py_id": 595409, "rappi_id": 257378, "mp_nombre": "Las Gracias Rotisería Palermo",     "dk": False, "codigo": None},
    {"nombre": "Las Gracias Rotisería Recoleta",     "marca": "Las Gracias", "grupo": "Santa Fe",          "py_id": 595511, "rappi_id": 257382, "mp_nombre": "Las Gracias Rotisería Recoleta",    "dk": False, "codigo": None},
    {"nombre": "Las Gracias Rotisería Caballito",    "marca": "Las Gracias", "grupo": "Formosa",           "py_id": 595293, "rappi_id": 257366, "mp_nombre": "Las Gracias Rotesería Caballito",   "dk": False, "codigo": None},
    {"nombre": "Las Gracias Rotisería Villa Urquiza","marca": "Las Gracias", "grupo": "Ávalos",            "py_id": 595376, "rappi_id": 257377, "mp_nombre": "Las Gracias Rotisería Villa Urquiza","dk": False, "codigo": None},
    {"nombre": "Las Gracias Rotisería Devoto",       "marca": "Las Gracias", "grupo": "Asunción",          "py_id": 595226, "rappi_id": 257380, "mp_nombre": "Las Gracias Rotisería Devoto",      "dk": False, "codigo": None},
    {"nombre": "Las Gracias Rotisería Martinez",     "marca": "Las Gracias", "grupo": "Martinez",          "py_id": 595268, "rappi_id": 257381, "mp_nombre": "Las Gracias Rotisería Martinez",    "dk": False, "codigo": None},

    # ── Tea Connection (locales con PedidosYa + Rappi) ───────────────────────
    {"nombre": "Tea Connection Dot",                  "marca": "Tea Connection", "grupo": "DOT",               "py_id": 507619,  "rappi_id": 226171, "mp_nombre": "Tea Connection Dot",        "dk": False, "codigo": None},
    {"nombre": "Tea Connection Puerto Madero",        "marca": "Tea Connection", "grupo": "Puerto Madero",     "py_id": 545208,  "rappi_id": 237996, "mp_nombre": None,                        "dk": False, "codigo": None},
    {"nombre": "Tea Connection Gorostiaga",           "marca": "Tea Connection", "grupo": "Gorostiaga",        "py_id": 119043,  "rappi_id": 111094, "mp_nombre": "Tea Connection Gorostiaga", "dk": False, "codigo": None},
    {"nombre": "Tea Connection Flores",               "marca": "Tea Connection", "grupo": "Flores",            "py_id": 542867,  "rappi_id": 238005, "mp_nombre": None,                        "dk": False, "codigo": None},
    {"nombre": "Tea Connection Villa Luro",           "marca": "Tea Connection", "grupo": "Villa Luro",        "py_id": 546270,  "rappi_id": 238481, "mp_nombre": None,                        "dk": False, "codigo": None},
    {"nombre": "Tea Connection Scalabrini",           "marca": "Tea Connection", "grupo": "Scalabrini",        "py_id": 135030,  "rappi_id": 125382, "mp_nombre": "Tea Connection Scalabrini", "dk": False, "codigo": None},
    {"nombre": "Tea Connection Abasto",               "marca": "Tea Connection", "grupo": "Abasto",            "py_id": 161520,  "rappi_id": 129921, "mp_nombre": "Tea Connection Abasto",     "dk": False, "codigo": None},
    {"nombre": "Tea Connection Uriburu",              "marca": "Tea Connection", "grupo": "Uriburu",           "py_id": 160447,  "rappi_id": 111294, "mp_nombre": "Tea Connection Uriburu",    "dk": False, "codigo": None},
    {"nombre": "Tea Connection Conde",                "marca": "Tea Connection", "grupo": "Conde",             "py_id": 119044,  "rappi_id": 115782, "mp_nombre": "Tea Connection Conde",      "dk": False, "codigo": None},
    {"nombre": "Tea Connection Montevideo",           "marca": "Tea Connection", "grupo": "Montevideo",        "py_id": 223,     "rappi_id": 114239, "mp_nombre": "Tea Connection Montevideo",  "dk": False, "codigo": None},
    {"nombre": "Tea Connection Vuelta De Obligado",   "marca": "Tea Connection", "grupo": "Vuelta de Obligado","py_id": 320846,  "rappi_id": 117038, "mp_nombre": "Tea Connection Belgrano",   "dk": False, "codigo": None},
    {"nombre": "Tea Connection Sinclair",             "marca": "Tea Connection", "grupo": "Sinclair",          "py_id": 119042,  "rappi_id": 111105, "mp_nombre": "Tea Connection Sinclair",   "dk": False, "codigo": None},
    {"nombre": "Tea Connection Ávalos",               "marca": "Tea Connection", "grupo": "Ávalos",            "py_id": 119045,  "rappi_id": 111876, "mp_nombre": "Tea Connection Avalos",     "dk": False, "codigo": None},
    {"nombre": "Tea Connection Libertador",           "marca": "Tea Connection", "grupo": "Libertador",        "py_id": 129017,  "rappi_id": 122879, "mp_nombre": "Tea Connection Libertador", "dk": False, "codigo": None},
    {"nombre": "Tea Connection Asunción",             "marca": "Tea Connection", "grupo": "Asunción",          "py_id": 254907,  "rappi_id": 151640, "mp_nombre": "Tea Connection Asunción",   "dk": False, "codigo": None},
    {"nombre": "Tea Connection Formosa",              "marca": "Tea Connection", "grupo": "Formosa",           "py_id": 119041,  "rappi_id": 111875, "mp_nombre": "Tea Connection Formosa",    "dk": False, "codigo": None},
    {"nombre": "Tea Connection Lacroze",              "marca": "Tea Connection", "grupo": "Lacroze",           "py_id": 226,     "rappi_id": 116438, "mp_nombre": "Tea Connection Lacroze",    "dk": False, "codigo": None},

    # ── Tea Connection Turbo (solo Rappi, sin PedidosYa) ─────────────────────
    {"nombre": "Tea Connection Turbo Gorostiaga",        "marca": "Tea Connection", "grupo": "Gorostiaga",        "py_id": None, "rappi_id": 226155, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Uriburu",           "marca": "Tea Connection", "grupo": "Uriburu",           "py_id": None, "rappi_id": 224951, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Conde",             "marca": "Tea Connection", "grupo": "Conde",             "py_id": None, "rappi_id": 224957, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Libertador",        "marca": "Tea Connection", "grupo": "Libertador",        "py_id": None, "rappi_id": 225113, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Vuelta de Obligado","marca": "Tea Connection", "grupo": "Vuelta de Obligado","py_id": None, "rappi_id": 226210, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Scalabrini",        "marca": "Tea Connection", "grupo": "Scalabrini",        "py_id": None, "rappi_id": 223109, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Formosa",           "marca": "Tea Connection", "grupo": "Formosa",           "py_id": None, "rappi_id": 222963, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Ávalos",            "marca": "Tea Connection", "grupo": "Ávalos",            "py_id": None, "rappi_id": 226214, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Lacroze",           "marca": "Tea Connection", "grupo": "Lacroze",           "py_id": None, "rappi_id": 222964, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Montevideo",        "marca": "Tea Connection", "grupo": "Montevideo",        "py_id": None, "rappi_id": 222969, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Sinclair",          "marca": "Tea Connection", "grupo": "Sinclair",          "py_id": None, "rappi_id": 223014, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Abasto",            "marca": "Tea Connection", "grupo": "Abasto",            "py_id": None, "rappi_id": 227169, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Pueyrredón",        "marca": "Tea Connection", "grupo": "Pueyrredon",        "py_id": None, "rappi_id": 228145, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Asunción",          "marca": "Tea Connection", "grupo": "Asunción",          "py_id": None, "rappi_id": 226204, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Tea Connection Turbo Dot",               "marca": "Tea Connection", "grupo": "DOT",               "py_id": None, "rappi_id": 227955, "mp_nombre": None, "dk": True, "codigo": None},

    # ── Green Eat (locales con PedidosYa + Rappi) ────────────────────────────
    {"nombre": "Green Eat Abasto",      "marca": "Green Eat", "grupo": "Abasto",      "py_id": 54149,  "rappi_id": 117698, "mp_nombre": "Green Eat Abasto",       "dk": False, "codigo": None},
    {"nombre": "Green Eat Florida",     "marca": "Green Eat", "grupo": "Florida",     "py_id": 195164, "rappi_id": 237979, "mp_nombre": "Green Eat Florida",      "dk": False, "codigo": None},
    {"nombre": "Green Eat Santa Fe",    "marca": "Green Eat", "grupo": "Santa Fe",    "py_id": 54151,  "rappi_id": 121087, "mp_nombre": "Green Eat Santa Fe",     "dk": False, "codigo": None},
    {"nombre": "Green Eat Ávalos",      "marca": "Green Eat", "grupo": "Ávalos",      "py_id": 506530, "rappi_id": 127690, "mp_nombre": "Green Eat Avalos",       "dk": False, "codigo": None},
    {"nombre": "Green Eat Asunción",    "marca": "Green Eat", "grupo": "Asunción",    "py_id": 251110, "rappi_id": 151636, "mp_nombre": "Green Eat Asunción",     "dk": False, "codigo": None},
    {"nombre": "Green Eat Cabildo",     "marca": "Green Eat", "grupo": "Cabildo",     "py_id": 64082,  "rappi_id": 117696, "mp_nombre": "Green Eat Cabildo",      "dk": False, "codigo": None},
    {"nombre": "Green Eat Rivadavia",   "marca": "Green Eat", "grupo": "Rivadavia",   "py_id": 54153,  "rappi_id": 117699, "mp_nombre": "Green Eat Rivadavia",    "dk": False, "codigo": None},
    {"nombre": "Green Eat Billinghurst","marca": "Green Eat", "grupo": "Billinghurst","py_id": 54150,  "rappi_id": 117697, "mp_nombre": "Green Eat Billinghurst", "dk": False, "codigo": None},
    {"nombre": "Green Eat Dot",         "marca": "Green Eat", "grupo": "DOT",         "py_id": 315467, "rappi_id": 117700, "mp_nombre": "Green Eat Dot",          "dk": False, "codigo": None},
    {"nombre": "Green Eat Sinclair",    "marca": "Green Eat", "grupo": "Sinclair",    "py_id": 253624, "rappi_id": 151528, "mp_nombre": "Green Eat Sinclair",     "dk": False, "codigo": None},
    {"nombre": "Green Eat Flores",      "marca": "Green Eat", "grupo": "Flores",      "py_id": 542865, "rappi_id": 237979, "mp_nombre": None,                     "dk": False, "codigo": None},
    {"nombre": "Green Eat Villa Luro",  "marca": "Green Eat", "grupo": "Villa Luro",  "py_id": 546437, "rappi_id": 238477, "mp_nombre": None,                     "dk": False, "codigo": None},
    {"nombre": "Green Eat Libertador",  "marca": "Green Eat", "grupo": "Libertador",  "py_id": 149209, "rappi_id": 127651, "mp_nombre": "Green Eat Libertador",   "dk": False, "codigo": None},
    {"nombre": "Green Eat Pueyrredón",  "marca": "Green Eat", "grupo": "Pueyrredon",  "py_id": None,   "rappi_id": None,   "mp_nombre": "Green Eat Pueyrredon",   "dk": False, "codigo": None},

    # ── Green Eat Turbo (solo Rappi) ─────────────────────────────────────────
    {"nombre": "Green Eat Turbo Asunción",    "marca": "Green Eat", "grupo": "Asunción",    "py_id": None, "rappi_id": 226207, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Green Eat Turbo Sinclair",    "marca": "Green Eat", "grupo": "Sinclair",    "py_id": None, "rappi_id": 225112, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Green Eat Turbo Ávalos",      "marca": "Green Eat", "grupo": "Ávalos",      "py_id": None, "rappi_id": 226213, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Green Eat Turbo Cabildo",     "marca": "Green Eat", "grupo": "Cabildo",     "py_id": None, "rappi_id": 219350, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Green Eat Turbo Florida",     "marca": "Green Eat", "grupo": "Florida",     "py_id": None, "rappi_id": 220481, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Green Eat Turbo Abasto",      "marca": "Green Eat", "grupo": "Abasto",      "py_id": None, "rappi_id": 221084, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Green Eat Turbo Libertador",  "marca": "Green Eat", "grupo": "Libertador",  "py_id": None, "rappi_id": 226206, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Green Eat Turbo Pueyrredón",  "marca": "Green Eat", "grupo": "Pueyrredon",  "py_id": None, "rappi_id": 226607, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Green Eat Turbo Rivadavia",   "marca": "Green Eat", "grupo": "Rivadavia",   "py_id": None, "rappi_id": 219368, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Green Eat Turbo Santa Fe",    "marca": "Green Eat", "grupo": "Santa Fe",    "py_id": None, "rappi_id": 220813, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Green Eat Turbo Billinghurst","marca": "Green Eat", "grupo": "Billinghurst","py_id": None, "rappi_id": 216559, "mp_nombre": None, "dk": True, "codigo": None},
    {"nombre": "Green Eat Turbo Dot",         "marca": "Green Eat", "grupo": "DOT",         "py_id": None, "rappi_id": 228142, "mp_nombre": None, "dk": True, "codigo": None},
]

# ── Cargar tiendas (Sheets > caché > hardcoded) ───────────────────────────────
TIENDAS = _cargar_tiendas(_TIENDAS_HARDCODED)

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


KEYWORDS_GRAVES = _cargar_keywords(_KEYWORDS_GRAVES_HARDCODED)


# ── Recarga dinámica (para usar desde la GUI sin reiniciar la app) ────────────

def recargar() -> None:
    """
    Vuelve a buscar tiendas y keywords desde Google Sheets y actualiza todas
    las variables del módulo.  Llamar al inicio de cada proceso para que
    cualquier cambio en el Sheet sea considerado sin necesidad de reiniciar.
    """
    global TIENDAS, KEYWORDS_GRAVES
    global RAPPI_INDEX, PY_INDEX, MP_INDEX
    global ALL_RAPPI_IDS, ALL_RAPPI_IDS_AR, ALL_PY_IDS, GRUPOS

    TIENDAS         = _cargar_tiendas(_TIENDAS_HARDCODED)
    KEYWORDS_GRAVES = _cargar_keywords(_KEYWORDS_GRAVES_HARDCODED)

    RAPPI_INDEX    = {t["rappi_id"]: t for t in TIENDAS if t["rappi_id"]}
    PY_INDEX       = {t["py_id"]:    t for t in TIENDAS if t["py_id"]}
    MP_INDEX       = {t["mp_nombre"]: t for t in TIENDAS if t["mp_nombre"]}

    ALL_RAPPI_IDS    = [str(t["rappi_id"])         for t in TIENDAS if t["rappi_id"]]
    ALL_RAPPI_IDS_AR = [f"AR{t['rappi_id']}"       for t in TIENDAS if t["rappi_id"]]