"""
Script de debug para la API de reclamos de Rappi.
Corre las dos llamadas (órdenes compensadas + detalles) y muestra el resultado crudo.

Uso:
    python debug_reclamos.py
"""
import sys, asyncio, json, logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

from datetime import datetime
from extractors.rappi import obtener_token, api_reclamos_ordenes, api_reclamos_detalles
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

    # ── 2. Órdenes compensadas ────────────────────────────────────────────────
    print(f"=== [2] api_reclamos_ordenes  ({DESDE.date()} → {HASTA.date()}) ===")
    entries = api_reclamos_ordenes(token, ALL_RAPPI_IDS, DESDE, HASTA)
    print(f"\nRESULTADO: {len(entries)} órdenes compensadas")

    if not entries:
        print(">>> SIN RESULTADOS — la API devolvió 0 entradas <<<\n")
        print("Posibles causas:")
        print("  - No hubo compensaciones en el período")
        print("  - El filtro 'order_status:eq: [COMPENSATIONS]' no matchea ninguna orden")
        print("  - Los store_ids no son correctos")
        print("  - La API usa otro campo de fecha (ej. settlement_date en lugar de order_date)")
    else:
        print("\nPrimeras 3 entradas (raw):")
        for e in entries[:3]:
            print(json.dumps(e, indent=2, default=str))

        # ── 3. Detalles de la primera orden ──────────────────────────────────
        print("\n=== [3] api_reclamos_detalles (primera orden) ===")
        primer_oid = str(entries[0].get("order_id", "")).strip()
        print(f"order_id a consultar: {primer_oid}")
        detalles = api_reclamos_detalles(token, ALL_RAPPI_IDS, [primer_oid])
        print(f"\nRESULTADO detalles: {json.dumps(detalles, indent=2, default=str)}")

    # ── 4. Prueba con rango extendido ─────────────────────────────────────────
    if not entries:
        print("\n=== [4] Reintentando con rango extendido (últimos 30 días)... ===")
        desde_ext = datetime(2026, 3, 25)
        entries_ext = api_reclamos_ordenes(token, ALL_RAPPI_IDS, desde_ext, HASTA)
        print(f"RESULTADO con rango extendido: {len(entries_ext)} órdenes")
        if entries_ext:
            from datetime import timezone, timedelta
            ARG = timedelta(hours=-3)
            fechas = []
            for e in entries_ext:
                ds = str(e.get("order_date", ""))
                for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                    try:
                        fechas.append(datetime.strptime(ds, fmt))
                        break
                    except ValueError:
                        pass
            if fechas:
                mas_reciente = max(fechas) + timedelta(hours=-3)  # convertir a ARG
                lag = HASTA - mas_reciente
                print(f"\nFecha más reciente disponible (hora ARG): {mas_reciente.strftime('%Y-%m-%d %H:%M')}")
                print(f"Lag de procesamiento estimado: {lag.days} días y {lag.seconds//3600} horas")
            print("\nÚltimas 5 fechas encontradas:")
            for e in entries_ext[:5]:
                print(f"  order_id={e.get('order_id')}  date={e.get('order_date')}  store={e.get('store_name')}")


if __name__ == "__main__":
    asyncio.run(main())
