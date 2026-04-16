"""
regenerar_pdfs.py — Regenera los PDFs a partir de un archivo Excel generado previamente.

No requiere acceso a las APIs de Rappi/PedidosYa ni a los CSVs de Mercado Libre.
Basta con el archivo Excel (.xlsx) que produce el sistema normalmente.

Uso (línea de comandos):
    python regenerar_pdfs.py resenas_2026-04-13.xlsx
    python regenerar_pdfs.py resenas_2026-04-13.xlsx --output ./mis_pdfs
    python regenerar_pdfs.py resenas_2026-04-13.xlsx --grupo Billinghurst

Uso (como módulo desde gui.py):
    from regenerar_pdfs import regenerar_desde_excel
    regenerar_desde_excel("ruta/al/excel.xlsx", output_dir="./informes",
                          log_fn=print, grupo_filtro=None)
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime
from collections import OrderedDict, defaultdict

# Asegurar que el módulo report/ sea importable
sys.path.insert(0, str(Path(__file__).parent))


# ── Lectura de hojas ──────────────────────────────────────────────────────────

def _leer_resenas_desde_hoja(ws, app: str) -> list[dict]:
    """
    Lee todas las reseñas de una hoja de aplicación (Rappi, PedidosYa o Mercado Libre).
    Las filas de datos empiezan en la fila 3 (fila 1 = título, fila 2 = encabezados).
    Columnas: Fecha y Hora | Nro Orden | Grupo/Local | Marca | Estrellas |
              Plato | Etiquetas | Comentario | Error Grave
    """
    resenas = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        orden_id = row[1]
        if not orden_id:
            continue  # fila vacía o fin de datos

        # Fecha (puede ser string o datetime según openpyxl)
        fecha_raw = row[0]
        fecha = None
        if fecha_raw:
            if isinstance(fecha_raw, datetime):
                fecha = fecha_raw
            else:
                for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
                    try:
                        fecha = datetime.strptime(str(fecha_raw), fmt)
                        break
                    except ValueError:
                        pass

        # Etiquetas: separadas por " | "
        etiquetas_raw = str(row[6]).strip() if row[6] else ""
        tags = [t.strip() for t in etiquetas_raw.split("|") if t.strip()] if etiquetas_raw else []

        # Error grave: celda contiene "SÍ" o "SI"
        grave_raw = str(row[8]).strip().upper() if row[8] else ""
        grave = grave_raw in ("SÍ", "SI", "SÌ", "S")

        resenas.append({
            "fecha":        fecha,
            "orden_id":     str(orden_id),
            "grupo_local":  str(row[2]) if row[2] else "",
            "marca":        str(row[3]) if row[3] else "",
            "app":          app,
            "estrellas":    int(row[4]) if row[4] else 1,
            "plato":        str(row[5]) if row[5] else "",
            "tags":         tags,
            "comentario":   str(row[7]) if row[7] else "",
            "grave":        grave,
        })

    return resenas


def _leer_reclamos_desde_hoja(ws) -> list[dict]:
    """
    Lee todos los reclamos de la hoja "Reclamos".
    Columnas: Fecha y Hora | Nro Orden | App | Grupo/Local | Marca |
              Platos Pedidos | Platos Reclamados | Motivo | Comentario del cliente
    """
    reclamos = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        orden_id = row[1]
        if not orden_id:
            continue

        fecha_raw = row[0]
        fecha = None
        if fecha_raw:
            if isinstance(fecha_raw, datetime):
                fecha = fecha_raw
            else:
                for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
                    try:
                        fecha = datetime.strptime(str(fecha_raw), fmt)
                        break
                    except ValueError:
                        pass

        reclamos.append({
            "fecha":             fecha,
            "orden_id":          str(orden_id),
            "app":               str(row[2]) if row[2] else "",
            "grupo_local":       str(row[3]) if row[3] else "",
            "marca":             str(row[4]) if row[4] else "",
            "platos_pedidos":    str(row[5]) if row[5] else "",
            "platos_reclamados": str(row[6]) if row[6] else "",
            "razon":             str(row[7]) if row[7] else "",
            "comentario":        str(row[8]) if row[8] else "",
        })

    return reclamos


def _leer_totales_desde_hoja(ws) -> dict[str, dict]:
    """
    Lee los totales por grupo desde la hoja "Totales".
    Columnas: Grupo/Local | Rappi | PedidosYa | Mercado Libre |
              Total Órdenes | Reseñas Negativas | Errores Graves | % Error
    """
    totales = {}
    for row in ws.iter_rows(min_row=3, values_only=True):
        grupo = row[0]
        if not grupo or str(grupo).strip().upper() == "TOTAL":
            continue

        def _int(v):
            try:
                return int(float(v)) if v is not None else 0
            except (ValueError, TypeError):
                return 0

        totales[str(grupo).strip()] = {
            "total_ordenes":      _int(row[4]),
            "resenas_negativas":  _int(row[5]),
            "errores_graves":     _int(row[6]),
        }

    return totales


# ── Adaptadores para build_report() ──────────────────────────────────────────

def _adaptar_resenas_para_pdf(resenas: list[dict]) -> list[dict]:
    """
    Convierte la lista plana de reseñas al formato de órdenes agrupadas
    que espera build_report() (múltiples platos por orden_id).
    """
    por_orden: OrderedDict = OrderedDict()
    for r in resenas:
        oid = r["orden_id"]
        if oid not in por_orden:
            por_orden[oid] = {
                "fecha":    r["fecha"].strftime("%d/%m/%Y %H:%M") if r["fecha"] else "",
                "orden":    oid,
                "marca":    r["marca"],
                "app":      r["app"],
                "estrellas": r["estrellas"],
                "platos":   [],
            }
        por_orden[oid]["platos"].append({
            "nombre":     r["plato"],
            "tags":       r["tags"],
            "comentario": r["comentario"],
            "grave":      r["grave"],
        })
    return list(por_orden.values())


def _adaptar_reclamos_para_pdf(reclamos: list[dict]) -> list[dict]:
    """
    Convierte la lista de reclamos al formato que espera build_report().
    """
    ordenados = sorted(reclamos, key=lambda r: r["fecha"] or datetime.min)
    return [
        {
            "fecha":             rc["fecha"].strftime("%d/%m/%Y %H:%M") if rc["fecha"] else "",
            "orden":             rc["orden_id"],
            "marca":             rc["marca"],
            "platos_pedidos":    rc["platos_pedidos"],
            "platos_reclamados": rc["platos_reclamados"],
            "razon":             rc["razon"],
            "comentario":        rc["comentario"],
        }
        for rc in ordenados
    ]


# ── Función principal ─────────────────────────────────────────────────────────

def regenerar_desde_excel(
    ruta_excel: str,
    output_dir: str = "./informes",
    log_fn=None,
    grupo_filtro: str = None,
) -> tuple[int, int]:
    """
    Lee el Excel y genera un PDF por cada grupo/local encontrado.

    Args:
        ruta_excel:    Ruta al archivo .xlsx generado por el sistema.
        output_dir:    Carpeta donde se guardarán los PDFs.
        log_fn:        Función de logging; recibe (mensaje, tag) donde
                       tag ∈ {"info","ok","warn","error","head"}.
                       Si es None se usa print().
        grupo_filtro:  Si se especifica, solo genera el PDF de ese grupo.

    Returns:
        (pdfs_generados, total_grupos)
    """
    from openpyxl import load_workbook
    from report.generador_pdf import build_report

    def log(msg, tag="info"):
        if log_fn:
            log_fn(msg, tag)
        else:
            prefijos = {"ok": "✓", "error": "✗", "warn": "!", "head": "─"}
            print(f"{prefijos.get(tag, ' ')} {msg}")

    ruta_excel = Path(ruta_excel)
    if not ruta_excel.exists():
        log(f"No se encontró el archivo: {ruta_excel}", "error")
        return 0, 0

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    log(f"Leyendo Excel: {ruta_excel.name}", "head")

    try:
        wb = load_workbook(ruta_excel, data_only=True)
    except Exception as e:
        log(f"No se pudo abrir el Excel: {e}", "error")
        return 0, 0

    # ── Leer reseñas de cada hoja de app ─────────────────────────────────────
    todas_resenas: list[dict] = []
    for app in ("Rappi", "PedidosYa", "Mercado Libre"):
        if app in wb.sheetnames:
            rs = _leer_resenas_desde_hoja(wb[app], app)
            todas_resenas.extend(rs)
            log(f"{app}: {len(rs)} reseñas", "info")
        else:
            log(f"{app}: hoja no encontrada — omitida", "warn")

    # ── Leer reclamos ─────────────────────────────────────────────────────────
    todos_reclamos: list[dict] = []
    if "Reclamos" in wb.sheetnames:
        todos_reclamos = _leer_reclamos_desde_hoja(wb["Reclamos"])
        log(f"Reclamos: {len(todos_reclamos)}", "info")

    # ── Leer totales ──────────────────────────────────────────────────────────
    totales: dict[str, dict] = {}
    if "Totales" in wb.sheetnames:
        totales = _leer_totales_desde_hoja(wb["Totales"])
        log(f"Totales: {len(totales)} grupos", "info")
    else:
        log("Hoja 'Totales' no encontrada — los indicadores estarán en 0", "warn")

    # ── Inferir fecha del nombre del archivo (resenas_YYYY-MM-DD.xlsx) ────────
    stem = ruta_excel.stem  # e.g. "resenas_2026-04-13"
    fecha_str_archivo = stem.replace("resenas_", "").strip()
    try:
        fecha_pdf = datetime.strptime(fecha_str_archivo, "%Y-%m-%d")
    except ValueError:
        fecha_pdf = datetime.now()
        log(f"No se pudo inferir la fecha del nombre '{stem}'; usando hoy.", "warn")

    fecha_display = f"{fecha_pdf.day}/{fecha_pdf.month}/{fecha_pdf.year}"

    # ── Agrupar por Grupo/Local ───────────────────────────────────────────────
    resenas_por_grupo: dict[str, list] = defaultdict(list)
    for r in todas_resenas:
        resenas_por_grupo[r["grupo_local"]].append(r)

    reclamos_por_grupo: dict[str, list] = defaultdict(list)
    for rc in todos_reclamos:
        reclamos_por_grupo[rc["grupo_local"]].append(rc)

    # Universo de grupos: unión de los que tienen reseñas + los de totales
    todos_grupos = sorted(set(resenas_por_grupo.keys()) | set(totales.keys()))

    if grupo_filtro:
        todos_grupos = [g for g in todos_grupos if g == grupo_filtro]
        if not todos_grupos:
            log(f"Grupo '{grupo_filtro}' no encontrado en el Excel.", "error")
            return 0, 0

    log(f"Generando {len(todos_grupos)} PDFs...", "head")

    pdfs_generados = 0
    for grupo in todos_grupos:
        resenas_g  = resenas_por_grupo.get(grupo, [])
        reclamos_g = reclamos_por_grupo.get(grupo, [])
        totales_g  = totales.get(grupo, {
            "total_ordenes": 0,
            "resenas_negativas": 0,
            "errores_graves": 0,
        })

        data = {
            "local":             grupo,
            "fecha":             fecha_display,
            "total_ordenes":     totales_g["total_ordenes"],
            "resenas_negativas": totales_g["resenas_negativas"],
            "errores_graves":    totales_g["errores_graves"],
            "resenas":           _adaptar_resenas_para_pdf(resenas_g),
            "reclamos":          _adaptar_reclamos_para_pdf(reclamos_g),
        }

        # Nombre del archivo PDF (mismo esquema que main.py)
        nombre_pdf = f"{grupo}_{fecha_str_archivo}.pdf"
        nombre_pdf = "".join(
            c if c.isalnum() or c in "._- " else "_" for c in nombre_pdf)
        ruta_pdf = output_path / nombre_pdf

        try:
            build_report(data, str(ruta_pdf))
            pdfs_generados += 1
            log(f"PDF generado: {nombre_pdf}", "ok")
        except Exception as e:
            log(f"Error generando PDF para '{grupo}': {e}", "error")

    log(f"Completado: {pdfs_generados}/{len(todos_grupos)} PDFs generados en {output_path.resolve()}", "head")
    return pdfs_generados, len(todos_grupos)


# ── Entrada por línea de comandos ─────────────────────────────────────────────

def _parse_args():
    p = argparse.ArgumentParser(
        description="Regenera PDFs de reseñas a partir de un Excel existente.")
    p.add_argument("excel",
                   help="Ruta al archivo Excel (.xlsx) generado por el sistema")
    p.add_argument("--output", default="./informes",
                   help="Carpeta de salida de los PDFs (default: ./informes)")
    p.add_argument("--grupo", default=None,
                   help="Nombre exacto del grupo a regenerar (opcional; default: todos)")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    ok, total = regenerar_desde_excel(
        ruta_excel=args.excel,
        output_dir=args.output,
        grupo_filtro=args.grupo,
    )
    sys.exit(0 if ok == total else 1)
