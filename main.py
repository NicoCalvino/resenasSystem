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
from processor.procesador   import Procesador
from report.generador_pdf   import build_report
from report.generador_excel import generar_excel
from config.models          import ResumenLocal

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


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

    # — PedidosYa
    if args.skip_peya:
        logger.info("── PedidosYa: omitido (desactivado desde la GUI)")
    else:
        logger.info("── Extrayendo PedidosYa...")
        try:
            rs, rcs, tots = await extraer_pedidosya(fecha_desde, fecha_hasta)
            todas_resenas.extend(rs)
            todos_reclamos.extend(rcs)
            for g, n in tots.items():
                totales_grupo[g] = totales_grupo.get(g, 0) + n
                totales_peya[g] = totales_peya.get(g, 0) + n
            logger.info(f"PedidosYa: {len(rs)} reseñas negativas, {len(rcs)} reclamos")
        except Exception as e:
            logger.error(f"PedidosYa falló: {e}")

        # — Reclamos PedidosYa (via webhook n8n)
        ruta_peya_reclamos = args.peya_reclamos or os.environ.get("PEYA_RECLAMOS_CSV")
        if not ruta_peya_reclamos:
            webhook_peya = os.environ.get("PEYA_RECLAMOS_WEBHOOK", "").strip().strip('"').strip("'")
            if webhook_peya:
                logger.info("── Descargando reclamos PedidosYa desde webhook n8n...")
                try:
                    ruta_peya_reclamos = descargar_reclamos_peya_webhook(webhook_peya)
                except Exception as e:
                    logger.error(f"PedidosYa reclamos: descarga desde webhook falló: {e}")

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
    if args.skip_rappi:
        logger.info("── Rappi: omitido (desactivado desde la GUI)")
    else:
        rappi_email    = os.environ.get("RAPPI_EMAIL")
        rappi_password = os.environ.get("RAPPI_PASSWORD")
        if rappi_email and rappi_password:
            logger.info("── Extrayendo Rappi...")
            try:
                rs, rcs, tots = await extraer_rappi(
                    rappi_email, rappi_password, fecha_desde, fecha_hasta, headless)
                todas_resenas.extend(rs)
                todos_reclamos.extend(rcs)
                for g, n in tots.items():
                    totales_grupo[g] = totales_grupo.get(g, 0) + n
                    totales_rappi[g] = totales_rappi.get(g, 0) + n
                logger.info(f"Rappi: {len(rs)} reseñas negativas, {len(rcs)} reclamos")
            except Exception as e:
                logger.error(f"Rappi falló: {e}")
        else:
            logger.warning("Rappi: credenciales no configuradas (RAPPI_EMAIL / RAPPI_PASSWORD)")

    # — Mercado Libre
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

        ruta_ml_reclamos = args.ml_reclamos or os.environ.get("ML_RECLAMOS_CSV")

        # Si no hay CSV manual, intentar descargar desde webhook de n8n
        if not ruta_ml_reclamos:
            webhook_url = os.environ.get("ML_RECLAMOS_WEBHOOK", "").strip().strip('"').strip("'")
            if webhook_url:
                logger.info("── Descargando reclamos ML desde webhook n8n...")
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

    # Totales ML (segundo CSV del Looker)
    ruta_ml_totales = args.mp_totales or encontrar_csv_totales("./mercadopago")
    if ruta_ml_totales:
        logger.info(f"── Procesando CSV Mercado Libre (totales): {ruta_ml_totales}")
        try:
            tots_ml = parsear_totales_ml(ruta_ml_totales)
            for g, n in tots_ml.items():
                totales_grupo[g] = totales_grupo.get(g, 0) + n
                totales_ml[g]    = tots_ml.get(g, 0)
            logger.info(f"Mercado Libre: totales cargados para {len(tots_ml)} grupos")
        except Exception as e:
            logger.error(f"Mercado Libre CSV totales falló: {e}")
    else:
        logger.info("Mercado Libre: no se encontró CSV de totales — omitiendo")
        logger.info("  → Colocá el CSV con 'total' en el nombre en ./mercadopago/")

    if not todas_resenas:
        logger.warning("Sin reseñas para procesar. Verificar credenciales y fechas.")
        return

    logger.info(f"\nTotal reseñas negativas: {len(todas_resenas)}")

    # ── procesamiento ──────────────────────────────────────────────────────────
    logger.info("── Procesando...")
    proc     = Procesador()
    resumenes: list[ResumenLocal] = proc.procesar(
        todas_resenas, totales_grupo, fecha_desde, fecha_hasta)

    # ── generación de PDFs ─────────────────────────────────────────────────────
    logger.info(f"── Generando {len(resumenes)} PDFs...")
    fecha_str = fecha_hasta.strftime("%Y-%m-%d")
    pdfs_generados = []

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
        }

        try:
            build_report(data, str(ruta_pdf))
            pdfs_generados.append(ruta_pdf)
            logger.info(f"  PDF: {ruta_pdf}")
        except Exception as e:
            logger.error(f"  Error generando PDF para {resumen.local_nombre}: {e}")

    # ── generación de Excel ───────────────────────────────────────────────────
    ruta_excel = output_dir / f"resenas_{fecha_str}.xlsx"
    try:
        generar_excel(
            resumenes=resumenes,
            todas_resenas=todas_resenas,
            totales_rappi=totales_rappi,
            totales_peya=totales_peya,
            totales_ml=totales_ml,
            ruta_salida=str(ruta_excel),
            reclamos=todos_reclamos if todos_reclamos else None,
        )
        logger.info(f"  Excel: {ruta_excel}")
    except Exception as e:
        logger.error(f"  Error generando Excel: {e}")

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
    """
    return [
        {
            "fecha":             rc.fecha_orden.strftime("%d/%m/%Y %H:%M"),
            "orden":             rc.orden_id,
            "app":               rc.app,
            "marca":             rc.marca,
            "platos_pedidos":    rc.platos_pedidos,
            "platos_reclamados": rc.platos_reclamados,
            "razon":             rc.razon,
            "comentario":        rc.comentario,
        }
        for rc in sorted(reclamos, key=lambda r: r.fecha_orden)
    ]


if __name__ == "__main__":
    asyncio.run(main())
