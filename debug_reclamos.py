"""
Script de debug para la API de reclamos de Rappi (endpoint /indicators/defects).
Corre una request por (store × tipo) y muestra el resultado crudo.

Uso:
    python debug_reclamos.py
"""
import sys, asyncio, json, logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

from datetime import datetime
from extractors.rappi import (
    obtener_token, api_defects, traer_defects_todos,
    convertir_reclamos, TIPOS_DEFECTO,
)
from config.locales import ALL_RAPPI_IDS

# ── Parámetros ────────────────────────────────────────────────────────────────
EMAIL    = 'nicolascalvino@gmail.com'
PASSWORD = 'RVc0Iq5t1X*y'
DESDE    = datetime(2026, 4, 20)
HASTA    = datetime(2026, 4, 24, 23, 59, 59)


async def main():
    # ── 1. Login ─────────────────────────────────────────────────────────────
    print("\n=== [1] Obteniendo token Rappi... ===")
    token = await obtener_token(EMAIL, PASSWORD, headless=True)
    print(f"Token OK ({len(token)} chars)\n")

    # ── 2. Probar una sola request (primer store, primer tipo) ────────────────
    primer_store = ALL_RAPPI_IDS[0] if ALL_RAPPI_IDS else None
    primer_tipo  = TIPOS_DEFECTO[0]
    if not primer_store:
        print(">>> No hay stores configurados en ALL_RAPPI_IDS <<<")
        return

    store_id_ar = f"AR{primer_store}"
    print(f"=== [2] api_defects ({store_id_ar}, {primer_tipo})  "
          f"{DESDE.date()} → {HASTA.date()} ===")
    entries = api_defects(token, store_id_ar, primer_tipo, DESDE, HASTA)
    print(f"\nRESULTADO: {len(entries)} entries")
    if entries:
        print("\nPrimeras 2 entradas (raw):")
        for e in entries[:2]:
            print(json.dumps(e, indent=2, default=str, ensure_ascii=False))

    # ── 3. Loop completo (todos los stores × todos los tipos) ─────────────────
    print(f"\n=== [3] traer_defects_todos "
          f"({len(ALL_RAPPI_IDS)} stores × {len(TIPOS_DEFECTO)} tipos) ===")
    todos = traer_defects_todos(token, ALL_RAPPI_IDS, DESDE, HASTA)
    print(f"\nRESULTADO total: {len(todos)} entries")

    # ── 4. Conversión al modelo ───────────────────────────────────────────────
    print("\n=== [4] convertir_reclamos ===")
    reclamos = convertir_reclamos(todos)
    print(f"\nRESULTADO: {len(reclamos)} reclamos convertidos")
    if reclamos:
        print("\nPrimeros 3 reclamos:")
        for rc in reclamos[:3]:
            print(f"  {rc.fecha_orden.strftime('%Y-%m-%d')}  "
                  f"local={rc.local_nombre}  orden={rc.orden_id}  "
                  f"razon={rc.razon}  platos={rc.platos_reclamados[:50]}...")


if __name__ == "__main__":
    asyncio.run(main())
