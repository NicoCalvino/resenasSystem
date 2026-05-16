"""
main.py — Orquestador principal del sistema de reseñas.

Uso:
    python main.py                        # ayer hasta hoy (modo normal)
    python main.py --desde 2026-03-31     # desde fecha específica
    python main.py --hasta 2026-04-01     # hasta fecha específica
    python main.py --mp-csv /ruta/mp.csv  # incluir CSV de Mercado Pago
    python main.py --headless false       # ver el browser durante el login

Variables de entorno requeridas:
    RAPPI_EMAIL, RAPPI_PASSWORD
    PEYA_EMAIL,  PEYA_PASSWORD

Salida:
    Un PDF por grupo/local en la carpeta ./informes/
"""
import asyncio, argparse, logging, os, sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv  # <-- 1. Importar la función

# ── setup path ────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from extractors.rappi        import extraer_rappi
from extractors.pedidosya    import (extraer_pedidosya,
                                     descargar_reclamos_peya_webhook,
                                     parsear_reclamos_peya_webhook)
from extractors.mercadopago  import (parsear_csv_ml, encontrar_csv_mas_reciente,
                                     parsear_totales_ml, encontrar_csv_totales,
                                     descargar_reclamos_desde_webhook)
from extractors.pedidos_sheets import calcular_totales_desde_sheets
from processor.procesador   import Procesador
from report.generador_pdf         import build_report
from report.generador_excel       import generar_excel
from report.generador_pdf_mensual import generar_pdfs_mensuales
from config.models          import ResumenLocal

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# ── Configuración del backfill histórico ─────────────────────────────────────
# Cantidad de días previos a fecha_hasta que se revisan en el backfill de
# reclamos para cada plataforma. Cambiar este valor afecta cuánto hacia atrás
# se busca cuando un día está sin verificar (o tiene 0 reclamos registrados).
DIAS_BACKFILL = 16


def parse_args():
    p = argparse.ArgumentParser(description="Sistema de reseñas negativas")
    p.add_argument("--desde",    default=None, help="Fecha inicio YYYY-MM-DD (default: ayer)")
    p.add_argument("--hasta",    default=None, help="Fecha fin YYYY-MM-DD (default: hoy)")
    p.add_argument("--mp-csv",        default=None, help="Ruta al CSV de reseñas de Mercado Libre")
    p.add_argument("--mp-totales",    default=None, help="Ruta al CSV de totales de Mercado Libre")
    p.add_argument("--ml-reclamos",   default=None,  help="Ruta al CSV de reclamos de Mercado Libre")
    p.add_argument("--peya-reclamos", default=None,  help="Ruta al CSV de reclamos de PedidosYa (webhook n8n)")
    p.add_argument("--skip-rappi",    action="store_true", help="Omitir extracción de Rappi")
    p.add_argument("--skip-peya",     action="store_true", help="Omitir extracción de PedidosYa")
    p.add_argument("--skip-ml",       action="store_true", help="Omitir extracción de Mercado Libre")
    p.add_argument("--skip-pdf",      action="store_true", help="Omitir generación de PDFs")
    p.add_argument("--skip-excel",    action="store_true", help="Omitir generación de Excel")
    p.add_argument("--headless", default="true", help="true/false — mostrar browser")
    p.add_argument("--solo-pdf", default=None, help="Generar PDF de prueba sin extracción (grupo)")
    p.add_argument("--output",   default="./informes", help="Carpeta de salida de PDFs")
    return p.parse_args()


async def main():
    args = parse_args()

    # ── fechas ────────────────────────────────────────────────────────────────
    hoy   = datetime.now().replace(hour=23, minute=59, second=59)
    ayer  = datetime.now().replace(hour=0,  minute=0,  second=0) - timedelta(days=1)

    fecha_desde = datetime.strptime(args.desde, "%Y-%m-%d") if args.desde else ayer
    fecha_hasta = datetime.strptime(args.hasta, "%Y-%m-%d").replace(
        hour=23, minute=59, second=59) if args.hasta else hoy
    headless = args.headless.lower() != "false"

    logger.info(f"Período: {fecha_desde.date()} → {fecha_hasta.date()}")

    # ── carpeta de salida ─────────────────────────────────────────────────────
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── extracción ────────────────────────────────────────────────────────────
    todas_resenas = []
    todos_reclamos = []    # reclamos Rappi (COMPENSATIONS)
    totales_grupo: dict[str, int] = {}

    totales_rappi:  dict[str, int] = {}
    totales_peya:   dict[str, int] = {}
    totales_ml:     dict[str, int] = {}

    # Totales por marca dentro de cada grupo: { grupo → { marca → ordenes } }
    totales_marca_por_grupo: dict[str, dict[str, int]] = {}

    # ── totales desde Google Sheets de pedidos ────────────────────────────────
    # Los totales de pedidos ya NO se extraen de las APIs de Rappi/PedidosYa;
    # se obtienen de la tabla centralizada de pedidos en Google Sheets.
    logger.info("── Calculando totales desde Google Sheets de pedidos...")
    try:
        totales_grupo, totales_marca_por_grupo, _tots_plat = \
            calcular_totales_desde_sheets(fecha_desde, fecha_hasta)
        # Distribuir en los contadores por plataforma para el Excel
        for plat, grupos in _tots_plat.items():
            plat_l = plat.lower()
            if "rappi" in plat_l:
                for g, n in grupos.items():
                    totales_rappi[g] = totales_rappi.get(g, 0) + n
            elif "pedidos" in plat_l or "peya" in plat_l:
                for g, n in grupos.items():
                    totales_peya[g] = totales_peya.get(g, 0) + n
            elif "mercado" in plat_l or "ml" in plat_l:
                for g, n in grupos.items():
                    totales_ml[g] = totales_ml.get(g, 0) + n
    except Exception as e:
        logger.error(f"Totales desde Sheets falló: {e}")

    # — PedidosYa
    ruta_peya_reclamos = None   # expuesta aquí para reutilizar en el backfill
    if args.skip_peya:
        logger.info("── PedidosYa: omitido (desactivado desde la GUI)")
    else:
        logger.info("── Extrayendo PedidosYa...")
        try:
            rs, rcs, _tots_peya, _tots_marca_peya = await extraer_pedidosya(fecha_desde, fecha_hasta)
            todas_resenas.extend(rs)
            todos_reclamos.extend(rcs)
            # Los totales de PedidosYa se ignoran: los totales vienen de Google Sheets
            logger.info(f"PedidosYa: {len(rs)} reseñas negativas, {len(rcs)} reclamos")
        except Exception as e:
            logger.error(f"PedidosYa falló: {e}")

        # — Reclamos PedidosYa (via Google Sheets publicado como CSV)
        ruta_peya_reclamos = args.peya_reclamos or os.environ.get("PEYA_RECLAMOS_CSV")
        if not ruta_peya_reclamos:
            webhook_peya = os.environ.get("PEYA_RECLAMOS_WEBHOOK", "").strip().strip('"').strip("'")
            if webhook_peya:
                logger.info("── Descargando reclamos PedidosYa desde Google Sheets...")
                try:
                    ruta_peya_reclamos = descargar_reclamos_peya_webhook(webhook_peya)
                except Exception as e:
                    logger.error(f"PedidosYa reclamos: descarga desde Google Sheets falló: {e}")

        if ruta_peya_reclamos:
            logger.info(f"── Procesando CSV reclamos PedidosYa: {ruta_peya_reclamos}")
            try:
                reclamos_peya = parsear_reclamos_peya_webhook(ruta_peya_reclamos, fecha_desde, fecha_hasta)
                todos_reclamos.extend(reclamos_peya)
                logger.info(f"PedidosYa reclamos: {len(reclamos_peya)} importados")
            except Exception as e:
                logger.error(f"PedidosYa CSV reclamos falló: {e}")
        else:
            logger.info("PedidosYa: no se proporcionó CSV de reclamos — omitiendo")
            logger.info("  → Configurá PEYA_RECLAMOS_WEBHOOK en .env o usá --peya-reclamos /ruta/archivo.csv")

    # — Rappi
    rappi_token = None   # se guarda para reutilizar en el backfill posterior
    if args.skip_rappi:
        logger.info("── Rappi: omitido (desactivado desde la GUI)")
    else:
        rappi_email    = os.environ.get("RAPPI_EMAIL")
        rappi_password = os.environ.get("RAPPI_PASSWORD")
        if rappi_email and rappi_password:
            logger.info("── Extrayendo Rappi...")
            try:
                rs, rcs, _tots_rappi, _tots_marca_rappi, rappi_token = await extraer_rappi(
                    rappi_email, rappi_password, fecha_desde, fecha_hasta, headless)
                todas_resenas.extend(rs)
                todos_reclamos.extend(rcs)
                # Los totales de Rappi se ignoran: los totales vienen de Google Sheets
                logger.info(f"Rappi: {len(rs)} reseñas negativas, {len(rcs)} reclamos")
                logger.info("Rappi: extraccion completada OK")
            except Exception as e:
                logger.error(f"Rappi falló: {e}")
                logger.error("Rappi: extraccion fallida")
        else:
            logger.warning("Rappi: credenciales no configuradas (RAPPI_EMAIL / RAPPI_PASSWORD)")

    # — Mercado Libre
    ruta_ml_reclamos = None     # expuesta aquí para reutilizar en el backfill
    if args.skip_ml:
        logger.info("── Mercado Libre: omitido (desactivado desde la GUI)")
    else:
        ruta_ml = args.mp_csv or encontrar_csv_mas_reciente("./mercadopago")
        if ruta_ml:
            logger.info(f"── Procesando CSV Mercado Libre (reseñas): {ruta_ml}")
            try:
                rs = parsear_csv_ml(ruta_ml, fecha_desde, fecha_hasta)
                todas_resenas.extend(rs)
                logger.info(f"Mercado Libre: {len(rs)} reseñas negativas")
            except Exception as e:
                logger.error(f"Mercado Libre CSV reseñas falló: {e}")
        else:
            logger.info("Mercado Libre: no se encontró CSV de reseñas — omitiendo")
            logger.info("  → Colocá el CSV en ./mercadopago/ o usá --mp-csv /ruta/archivo.csv")

        ruta_ml_reclamos = args.ml_reclamos or os.environ.get("ML_RECLAMOS_CSV") or ruta_ml_reclamos

        # Si no hay CSV manual, intentar descargar desde webhook de n8n
        if not ruta_ml_reclamos:
            webhook_url = os.environ.get("ML_RECLAMOS_WEBHOOK", "").strip().strip('"').strip("'")
            if webhook_url:
                logger.info("── Descargando reclamos ML desde webhook Apps Script...")
                try:
                    ruta_ml_reclamos = descargar_reclamos_desde_webhook(webhook_url)
                except Exception as e:
                    logger.error(f"Mercado Libre reclamos: descarga desde webhook falló: {e}")

        if ruta_ml_reclamos:
            logger.info(f"── Procesando CSV reclamos Mercado Libre: {ruta_ml_reclamos}")
            try:
                from extractors.mercadopago import parsear_reclamos_ml
                reclamos_ml = parsear_reclamos_ml(ruta_ml_reclamos, fecha_desde, fecha_hasta)
                todos_reclamos.extend(reclamos_ml)
                logger.info(f"Mercado Libre reclamos: {len(reclamos_ml)} importados")
            except Exception as e:
                logger.error(f"Mercado Libre CSV reclamos falló: {e}")
        else:
            logger.info("Mercado Libre: no se proporcionó CSV de reclamos — omitiendo")
            logger.info("  → Configurá ML_RECLAMOS_WEBHOOK en .env o usá --ml-reclamos /ruta/archivo.csv")

    # Totales ML (CSV del Looker) — ya no se usan: los totales vienen de Google Sheets.
    # Se mantiene el código comentado por si se necesita en el futuro.
    # ruta_ml_totales = args.mp_totales or encontrar_csv_totales("./mercadopago")
    # if ruta_ml_totales: ...
    logger.info("Mercado Libre: totales omitidos (se usan los de Google Sheets de pedidos)")

    if not todas_resenas:
        logger.warning("Sin reseñas para procesar. Verificar credenciales y fechas.")
        return

    logger.info(f"\nTotal reseñas negativas: {len(todas_resenas)}")

    # ── histórico de reclamos ──────────────────────────────────────────────────
    logger.info("── Registrando histórico de reclamos...")
    try:
        from config.historico import registrar_ejecucion
        registrar_ejecucion(
            reclamos=todos_reclamos,
            fecha_ejecucion=fecha_hasta,
        )
    except Exception as e:
        logger.error(f"Histórico: error inesperado: {e}")

    # ── Backfill de reclamos (ventana configurable, todas las plataformas) ───────
    # Para cada plataforma se verifica que los últimos DIAS_BACKFILL días tengan
    # sus reclamos guardados en el histórico. Los días faltantes (o los que
    # quedaron con 0 reclamos en una corrida previa) se descargan/parsean y se
    # guardan silenciosamente sin afectar el informe del período actual.
    try:
        from config.historico import (obtener_dias_no_verificados,
                                      marcar_dias_verificados,
                                      registrar_ejecucion as _registrar)

        # Ventana de backfill: DIAS_BACKFILL días previos a fecha_hasta
        _ventana_desde = (fecha_hasta - timedelta(days=DIAS_BACKFILL)).replace(
            hour=0, minute=0, second=0, microsecond=0)

        # Días del reporte actual → se marcan verificados en todas las plataformas
        dias_reporte: list[str] = []
        _curr = fecha_desde.date()
        while _curr <= fecha_hasta.date():
            dias_reporte.append(_curr.strftime("%Y-%m-%d"))
            _curr += timedelta(days=1)
        dias_reporte_set = set(dias_reporte)

        # ── Rappi ──────────────────────────────────────────────────────────────
        if rappi_token:
            logger.info(f"── Backfill Rappi (ventana {DIAS_BACKFILL} días)...")
            try:
                from extractors.rappi import backfill_reclamos_dia

                marcar_dias_verificados("rappi", dias_reporte)
                dias_faltantes_rappi = [
                    d for d in obtener_dias_no_verificados("rappi", _ventana_desde, fecha_hasta)
                    if d not in dias_reporte_set
                ]
                if dias_faltantes_rappi:
                    logger.info(
                        f"Rappi backfill: {len(dias_faltantes_rappi)} días sin verificar "
                        f"→ {dias_faltantes_rappi}")
                    for dia_str in dias_faltantes_rappi:
                        dia_dt = datetime.strptime(dia_str, "%Y-%m-%d")
                        try:
                            reclamos_dia = await backfill_reclamos_dia(rappi_token, dia_dt)
                            _registrar(reclamos=reclamos_dia, fecha_ejecucion=dia_dt)
                            marcar_dias_verificados("rappi", [dia_str])
                            logger.info(
                                f"Rappi backfill {dia_str}: "
                                f"{len(reclamos_dia)} reclamos guardados en histórico")
                        except Exception as e:
                            logger.error(f"Rappi backfill {dia_str} falló: {e}")
                else:
                    logger.info("Rappi backfill: todos los días ya verificados")
            except Exception as e:
                logger.error(f"Rappi backfill: error inesperado: {e}")

        # ── PedidosYa ──────────────────────────────────────────────────────────
        if not args.skip_peya and ruta_peya_reclamos:
            logger.info(f"── Backfill PedidosYa (ventana {DIAS_BACKFILL} días)...")
            try:
                marcar_dias_verificados("pedidosya", dias_reporte)
                dias_faltantes_peya = [
                    d for d in obtener_dias_no_verificados("pedidosya", _ventana_desde, fecha_hasta)
                    if d not in dias_reporte_set
                ]
                if dias_faltantes_peya:
                    logger.info(
                        f"PedidosYa backfill: {len(dias_faltantes_peya)} días sin verificar "
                        f"→ {dias_faltantes_peya}")
                    # El CSV tiene datos históricos: se parsea una sola vez para
                    # todo el rango faltante (más eficiente que hacerlo día a día).
                    bf_desde_peya = datetime.strptime(dias_faltantes_peya[0],  "%Y-%m-%d")
                    bf_hasta_peya = datetime.strptime(dias_faltantes_peya[-1], "%Y-%m-%d").replace(
                        hour=23, minute=59, second=59)
                    reclamos_bf_peya = parsear_reclamos_peya_webhook(
                        ruta_peya_reclamos, bf_desde_peya, bf_hasta_peya)
                    _registrar(reclamos=reclamos_bf_peya, fecha_ejecucion=bf_hasta_peya)
                    marcar_dias_verificados("pedidosya", dias_faltantes_peya)
                    logger.info(
                        f"PedidosYa backfill: {len(reclamos_bf_peya)} reclamos guardados "
                        f"en histórico para {len(dias_faltantes_peya)} días")
                else:
                    logger.info("PedidosYa backfill: todos los días ya verificados")
            except Exception as e:
                logger.error(f"PedidosYa backfill: error inesperado: {e}")

        # ── Mercado Libre ──────────────────────────────────────────────────────
        if not args.skip_ml and ruta_ml_reclamos:
            logger.info(f"── Backfill Mercado Libre (ventana {DIAS_BACKFILL} días)...")
            try:
                from extractors.mercadopago import parsear_reclamos_ml as _parsear_ml

                marcar_dias_verificados("ml", dias_reporte)
                dias_faltantes_ml = [
                    d for d in obtener_dias_no_verificados("ml", _ventana_desde, fecha_hasta)
                    if d not in dias_reporte_set
                ]
                if dias_faltantes_ml:
                    logger.info(
                        f"ML backfill: {len(dias_faltantes_ml)} días sin verificar "
                        f"→ {dias_faltantes_ml}")
                    bf_desde_ml = datetime.strptime(dias_faltantes_ml[0],  "%Y-%m-%d")
                    bf_hasta_ml = datetime.strptime(dias_faltantes_ml[-1], "%Y-%m-%d").replace(
                        hour=23, minute=59, second=59)
                    reclamos_bf_ml = _parsear_ml(ruta_ml_reclamos, bf_desde_ml, bf_hasta_ml)
                    _registrar(reclamos=reclamos_bf_ml, fecha_ejecucion=bf_hasta_ml)
                    marcar_dias_verificados("ml", dias_faltantes_ml)
                    logger.info(
                        f"ML backfill: {len(reclamos_bf_ml)} reclamos guardados "
                        f"en histórico para {len(dias_faltantes_ml)} días")
                else:
                    logger.info("ML backfill: todos los días ya verificados")
            except Exception as e:
                logger.error(f"ML backfill: error inesperado: {e}")

    except Exception as e:
        logger.error(f"Backfill histórico: error general inesperado: {e}")

    # ── procesamiento ──────────────────────────────────────────────────────────
    logger.info("── Procesando...")
    proc     = Procesador()
    resumenes: list[ResumenLocal] = proc.procesar(
        todas_resenas, totales_grupo, fecha_desde, fecha_hasta,
        reclamos=todos_reclamos)

    # ── generación de PDFs ─────────────────────────────────────────────────────
    fecha_str = fecha_hasta.strftime("%Y-%m-%d")
    pdfs_generados = []

    if args.skip_pdf:
        logger.info("── Generación de PDFs omitida (--skip-pdf)")
    else:
        logger.info(f"── Generando {len(resumenes)} PDFs...")

        # Mapa reclamos por local para lookup rápido en el loop de PDFs
        reclamos_por_local: dict[str, list] = {}
        for rc in todos_reclamos:
            reclamos_por_local.setdefault(rc.local_id, []).append(rc)

        for resumen in resumenes:
            nombre_archivo = f"{resumen.local_nombre}_{fecha_str}.pdf"
            # limpiar caracteres no válidos para nombres de archivo
            nombre_archivo = "".join(
                c if c.isalnum() or c in "._- " else "_" for c in nombre_archivo)
            ruta_pdf = output_dir / nombre_archivo

            # adaptar ResumenLocal al formato que espera generador_pdf
            data = {
                "local":              resumen.local_nombre,
                "fecha":              f"{fecha_hasta.day}/{fecha_hasta.month}/{fecha_hasta.year}",
                "total_ordenes":      resumen.total_ordenes,
                "resenas_negativas":  resumen.resenas_negativas,
                "errores_graves":     resumen.errores_graves,
                "resenas":            _adaptar_resenas(resumen.resenas),
                "reclamos":           _adaptar_reclamos(reclamos_por_local.get(resumen.local_id, [])),
                # Totales por marca para el desglose en el PDF (Las Gracias / Green Eat / Tea Connection)
                "totales_por_marca":  totales_marca_por_grupo.get(resumen.local_id, {}),
            }

            try:
                build_report(data, str(ruta_pdf))
                pdfs_generados.append(ruta_pdf)
                logger.info(f"  PDF: {ruta_pdf}")
            except Exception as e:
                logger.error(f"  Error generando PDF para {resumen.local_nombre}: {e}")

    # ── generación de Excel ───────────────────────────────────────────────────
    if args.skip_excel:
        logger.info("── Generación de Excel omitida (--skip-excel)")
    else:
        timestamp = datetime.now().strftime("%H%M%S")
        ruta_excel = output_dir / f"informe_{fecha_str}_{timestamp}.xlsx"
        try:
            generar_excel(
                resumenes=resumenes,
                todas_resenas=todas_resenas,
                totales_rappi=totales_rappi,
                totales_peya=totales_peya,
                totales_ml=totales_ml,
                ruta_salida=str(ruta_excel),
                reclamos=todos_reclamos if todos_reclamos else None,
                totales_marca_por_grupo=totales_marca_por_grupo,
            )
            logger.info(f"  Excel: {ruta_excel}")
        except Exception as e:
            logger.error(f"  Error generando Excel: {e}")

    # ── PDFs mensuales (6 grupos Marca × DK) ─────────────────────────────────
    if args.skip_pdf:
        logger.info("── PDFs mensuales omitidos (--skip-pdf)")
    else:
        logger.info("── Generando PDFs mensuales de reclamos por grupo...")
        try:
            pdfs_mensuales = generar_pdfs_mensuales(
                output_dir=str(output_dir),
                anio=fecha_hasta.year,
                mes=fecha_hasta.month,
                fecha_hasta=fecha_hasta,
            )
            logger.info(f"  PDFs mensuales generados: {len(pdfs_mensuales)}")
            for p in pdfs_mensuales:
                logger.info(f"  Mensual: {p}")
        except Exception as e:
            logger.error(f"  Error generando PDFs mensuales: {e}")

    # ── resumen final ──────────────────────────────────────────────────────────
    logger.info(f"\n{'='*50}")
    logger.info(f"COMPLETADO")
    logger.info(f"  Período:          {fecha_desde.date()} → {fecha_hasta.date()}")
    logger.info(f"  Grupos procesados: {len(resumenes)}")
    logger.info(f"  PDFs generados:    {len(pdfs_generados)}")
    logger.info(f"  Carpeta:           {output_dir.resolve()}")
    logger.info(f"{'='*50}")


def _adaptar_resenas(resenas):
    """
    Convierte lista de Resena al formato dict que espera build_report().
    Agrupa por orden_id para que el PDF muestre órdenes consolidadas.
    """
    from collections import OrderedDict
    por_orden = OrderedDict()
    for r in resenas:
        if r.orden_id not in por_orden:
            por_orden[r.orden_id] = {
                "fecha":    r.fecha_orden.strftime("%d/%m/%Y %H:%M") if r.fecha_orden else "",
                "orden":    r.orden_id,
                "marca":    r.marca,
                "app":      r.app,
                "estrellas": r.estrellas,
                "platos":   [],
            }
        por_orden[r.orden_id]["platos"].append({
            "nombre":    r.plato,
            "tags":      r.tags,
            "comentario": r.comentario,
            "grave":     r.es_error_grave,
        })
    return list(por_orden.values())


def _adaptar_reclamos(reclamos):
    """
    Convierte lista de Reclamo al formato dict que espera build_report().
    El campo 'inaceptable' se calcula aplicando la detección de keywords graves
    al comentario y razón del reclamo.
    Se deduplica por orden_id para evitar que órdenes con múltiples platos
    aparezcan repetidas cuando el CSV del webhook genera una fila por plato.
    """
    from processor.procesador import es_error_grave
    vistos = set()
    result = []
    for rc in sorted(reclamos, key=lambda r: r.fecha_orden):
        key = (rc.orden_id, rc.local_id)
        if key in vistos:
            continue
        vistos.add(key)
        result.append({
            "fecha":             rc.fecha_orden.strftime("%d/%m/%Y %H:%M"),
            "orden":             rc.orden_id,
            "app":               rc.app,
            "marca":             rc.marca,
            "platos_pedidos":    rc.platos_pedidos,
            "platos_reclamados": rc.platos_reclamados,
            "razon":             rc.razon,
            "comentario":        rc.comentario,
            "inaceptable":       es_error_grave(rc.comentario or "", [rc.razon or ""]),
        })
    return result

if __name__ == "__main__":
    asyncio.run(main())
