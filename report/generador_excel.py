"""
Generador de Excel con reporte completo del proceso.
Pestañas: Rappi | PedidosYa | Mercado Libre | Totales por grupo
"""
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import datetime

from config.models import Resena, Reclamo, ResumenLocal

# ── Colores ───────────────────────────────────────────────────────────────────
COLOR_HEADER_APP   = {"Rappi": "FF6900", "PedidosYa": "FA0050", "Mercado Libre": "FFE600"}
COLOR_HEADER_TEXT  = {"Rappi": "FFFFFF", "PedidosYa": "FFFFFF", "Mercado Libre": "333333"}
COLOR_GRAVE_BG     = "FFE0E0"
COLOR_HEADER_TOT   = "1A1A2E"
COLOR_SUBHEAD_TOT  = "16213E"
COLOR_ALT_ROW      = "F8F8F8"

_thin = Side(style="thin", color="CCCCCC")
_border = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def _header_style(bg: str, fg: str = "FFFFFF", bold=True, size=10):
    font = Font(name="Arial", bold=bold, color=fg, size=size)
    fill = PatternFill("solid", start_color=bg)
    align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    return font, fill, align


def _set_row(ws, row_idx, values, font=None, fill=None, align=None, border=None):
    for col, val in enumerate(values, 1):
        cell = ws.cell(row=row_idx, column=col, value=val)
        if font:   cell.font   = font
        if fill:   cell.fill   = fill
        if align:  cell.alignment = align
        if border: cell.border = border


def _autowidth(ws, min_w=8, max_w=50):
    for col in ws.columns:
        length = max(
            (len(str(c.value)) if c.value else 0) for c in col
        )
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max(length + 2, min_w), max_w)


# ── Pestaña por aplicación ────────────────────────────────────────────────────
COLS_APP = [
    "Fecha y Hora", "Nro Orden", "Grupo/Local", "Marca", "Estrellas",
    "Plato", "Etiquetas", "Comentario", "Error Grave"
]

def _escribir_hoja_app(ws, app: str, resenas: list[Resena]):
    color_bg = COLOR_HEADER_APP.get(app, "444444")
    color_fg = COLOR_HEADER_TEXT.get(app, "FFFFFF")
    font_h, fill_h, align_h = _header_style(color_bg, color_fg, size=10)

    # Título
    ws.merge_cells(f"A1:{get_column_letter(len(COLS_APP))}1")
    title_cell = ws["A1"]
    title_cell.value = f"{app} — Reseñas negativas (1-2 estrellas)"
    title_cell.font  = Font(name="Arial", bold=True, size=12, color=color_fg)
    title_cell.fill  = PatternFill("solid", start_color=color_bg)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 22

    # Encabezados
    _set_row(ws, 2, COLS_APP, font=font_h, fill=fill_h, align=align_h, border=_border)
    ws.row_dimensions[2].height = 18
    ws.freeze_panes = "A3"

    # Datos
    font_d = Font(name="Arial", size=9)
    font_g = Font(name="Arial", size=9, color="CC0000", bold=True)
    align_d = Alignment(vertical="center", wrap_text=True)
    fill_alt  = PatternFill("solid", start_color=COLOR_ALT_ROW)
    fill_grave= PatternFill("solid", start_color=COLOR_GRAVE_BG)

    for i, r in enumerate(resenas, 3):
        grave = r.es_error_grave
        fill_row = fill_grave if grave else (fill_alt if i % 2 == 0 else None)
        font_row = font_g if grave else font_d

        values = [
            r.fecha_orden.strftime("%d/%m/%Y %H:%M") if r.fecha_orden else "",
            r.orden_id,
            r.local_nombre,
            r.marca,
            r.estrellas,
            r.plato,
            " | ".join(r.tags) if r.tags else "",
            r.comentario,
            "SÍ" if grave else "",
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=i, column=col, value=val)
            cell.font      = font_row
            cell.alignment = align_d
            cell.border    = _border
            if fill_row:
                cell.fill = fill_row

        ws.row_dimensions[i].height = 15

    # Anchos fijos
    anchos = [16, 16, 16, 16, 9, 28, 28, 45, 10]
    for col, w in enumerate(anchos, 1):
        ws.column_dimensions[get_column_letter(col)].width = w

    return len(resenas)


# ── Pestaña de reclamos (Rappi + PedidosYa) ──────────────────────────────────
COLS_RECLAMOS = [
    "Fecha y Hora", "Nro Orden", "App", "Grupo/Local", "Marca",
    "Platos Pedidos", "Platos Reclamados", "Motivo", "Comentario del cliente"
]

def _escribir_hoja_reclamos(ws, reclamos: list[Reclamo]):
    color_bg = "444444"   # gris oscuro neutro (no solo Rappi)
    color_fg = "FFFFFF"
    font_h, fill_h, align_h = _header_style(color_bg, color_fg, size=10)

    # Título
    ws.merge_cells(f"A1:{get_column_letter(len(COLS_RECLAMOS))}1")
    title_cell = ws["A1"]
    title_cell.value = "Reclamos / Compensaciones"
    title_cell.font  = Font(name="Arial", bold=True, size=12, color=color_fg)
    title_cell.fill  = PatternFill("solid", start_color=color_bg)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 22

    # Encabezados
    _set_row(ws, 2, COLS_RECLAMOS, font=font_h, fill=fill_h, align=align_h, border=_border)
    ws.row_dimensions[2].height = 18
    ws.freeze_panes = "A3"

    # Datos
    font_d  = Font(name="Arial", size=9)
    align_d = Alignment(vertical="center", wrap_text=True)
    fill_alt = PatternFill("solid", start_color=COLOR_ALT_ROW)

    # Ordenar por app, grupo y fecha
    reclamos_ord = sorted(reclamos, key=lambda r: (r.app, r.local_nombre, r.fecha_orden))

    for i, r in enumerate(reclamos_ord, 3):
        fill_row = fill_alt if i % 2 == 0 else None

        values = [
            r.fecha_orden.strftime("%d/%m/%Y %H:%M"),
            r.orden_id,
            r.app,
            r.local_nombre,
            r.marca,
            r.platos_pedidos,
            r.platos_reclamados,
            r.razon,
            r.comentario,
        ]
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=i, column=col, value=val)
            cell.font      = font_d
            cell.alignment = align_d
            cell.border    = _border
            if fill_row:
                cell.fill = fill_row

        ws.row_dimensions[i].height = 15

    # Anchos fijos
    anchos = [16, 16, 12, 16, 16, 40, 30, 36, 45]
    for col, w in enumerate(anchos, 1):
        ws.column_dimensions[get_column_letter(col)].width = w

    return len(reclamos_ord)


# ── Pestaña de totales ────────────────────────────────────────────────────────
def _escribir_hoja_totales(ws, resumenes: list[ResumenLocal],
                            totales_rappi: dict, totales_peya: dict,
                            totales_ml: dict):
    # Encabezado principal
    ws.merge_cells("A1:H1")
    c = ws["A1"]
    c.value = "Totales de órdenes por grupo y aplicación"
    c.font  = Font(name="Arial", bold=True, size=12, color="FFFFFF")
    c.fill  = PatternFill("solid", start_color=COLOR_HEADER_TOT)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 22

    # Encabezados de columna
    cols = ["Grupo/Local", "Rappi", "PedidosYa", "Mercado Libre",
            "Total Órdenes", "Reseñas Negativas", "Errores Graves", "% Error"]
    font_h, fill_h, align_h = _header_style(COLOR_SUBHEAD_TOT, "FFFFFF", size=10)
    _set_row(ws, 2, cols, font=font_h, fill=fill_h, align=align_h, border=_border)
    ws.row_dimensions[2].height = 18
    ws.freeze_panes = "A3"

    # Recopilar todos los grupos
    grupos = sorted(set(
        list(totales_rappi.keys()) +
        list(totales_peya.keys()) +
        list(totales_ml.keys()) +
        [r.local_nombre for r in resumenes]
    ))

    # Mapa resumen por grupo
    mapa = {r.local_nombre: r for r in resumenes}

    font_d  = Font(name="Arial", size=9)
    font_b  = Font(name="Arial", size=9, bold=True)
    align_c = Alignment(horizontal="center", vertical="center")
    align_l = Alignment(horizontal="left",   vertical="center")
    fill_alt= PatternFill("solid", start_color=COLOR_ALT_ROW)

    for i, grupo in enumerate(grupos, 3):
        fill_row = fill_alt if i % 2 == 0 else None

        r_rappi = totales_rappi.get(grupo, 0)
        r_peya  = totales_peya.get(grupo, 0)
        r_ml    = totales_ml.get(grupo, 0)
        total   = r_rappi + r_peya + r_ml

        resumen = mapa.get(grupo)
        neg     = resumen.resenas_negativas if resumen else 0
        graves  = resumen.errores_graves    if resumen else 0

        # % error con IFERROR para evitar DIV/0
        col_tot = get_column_letter(5)  # columna E = Total Órdenes
        col_neg = get_column_letter(6)  # columna F = Reseñas Negativas
        pct_formula = f"=IFERROR({col_neg}{i}/{col_tot}{i},0)"

        row_vals = [grupo, r_rappi, r_peya, r_ml, total, neg, graves, pct_formula]

        for col, val in enumerate(row_vals, 1):
            cell = ws.cell(row=i, column=col, value=val)
            cell.border = _border
            if fill_row:
                cell.fill = fill_row
            if col == 1:
                cell.font = font_b
                cell.alignment = align_l
            else:
                cell.font = font_d
                cell.alignment = align_c

        # Formato de porcentaje en columna H
        ws.cell(row=i, column=8).number_format = "0.0%"
        ws.row_dimensions[i].height = 15

    # Fila de totales
    last = len(grupos) + 2
    tot_row = last + 1
    ws.cell(row=tot_row, column=1, value="TOTAL").font = Font(name="Arial", bold=True, size=10)
    for col in range(2, 8):
        letter = get_column_letter(col)
        cell = ws.cell(row=tot_row, column=col,
                       value=f"=SUM({letter}3:{letter}{last})")
        cell.font = Font(name="Arial", bold=True, size=10)
        cell.fill = PatternFill("solid", start_color="E8E8E8")
        cell.border = _border
        cell.alignment = Alignment(horizontal="center")
    ws.cell(row=tot_row, column=8).number_format = "0.0%"

    # Anchos
    for col, w in zip(range(1, 9), [22, 12, 12, 14, 14, 16, 14, 10]):
        ws.column_dimensions[get_column_letter(col)].width = w


# ── Función principal ─────────────────────────────────────────────────────────
def generar_excel(
    resumenes: list[ResumenLocal],
    todas_resenas: list[Resena],
    totales_rappi: dict[str, int],
    totales_peya:  dict[str, int],
    totales_ml:    dict[str, int],
    ruta_salida: str,
    reclamos: list[Reclamo] = None,
):
    wb = Workbook()
    wb.remove(wb.active)   # quitar hoja vacía por defecto

    apps = ["Rappi", "PedidosYa", "Mercado Libre"]

    for app in apps:
        ws = wb.create_sheet(title=app)
        resenas_app = [r for r in todas_resenas if r.app == app]
        # Ordenar por grupo y fecha
        resenas_app.sort(key=lambda r: (r.local_nombre, r.fecha_orden or datetime.min))
        n = _escribir_hoja_app(ws, app, resenas_app)

    # Pestaña de reclamos combinados (Rappi + PedidosYa, si hay datos)
    if reclamos:
        ws_rec = wb.create_sheet(title="Reclamos")
        _escribir_hoja_reclamos(ws_rec, reclamos)

    # Pestaña de totales
    ws_tot = wb.create_sheet(title="Totales")
    _escribir_hoja_totales(ws_tot, resumenes, totales_rappi, totales_peya, totales_ml)

    wb.save(ruta_salida)
    return ruta_salida
