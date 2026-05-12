"""
Informes mensuales de reclamos por grupo (Marca × DK).

Genera 6 PDFs — uno por cada combinación de Marca × DK:
  1. Tea Connection No DK
  2. Tea Connection DK
  3. Green Eat No DK
  4. Green Eat DK
  5. Las Gracias No DK
  6. Las Gracias DK

Fuente: historico.json (acumulado mensual en Google Drive / ruta local)

Contenido de cada PDF:
  - Encabezado: nombre del grupo, mes en curso, total de pedidos
  - Widget de reclamos: gauge % + breakdown CALIDAD/EQUIVOCADO/INCOMPLETO + sello verde/rojo
  - Gráfico de evolución diaria (% reclamos por día, línea umbral en 2%)
  - Tabla: LOCAL | Q. PEDIDOS | Q. RECLAMOS | % RECLAMOS
"""

import io
import calendar
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    KeepTogether, Flowable, Table, TableStyle,
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

# ── Importar constantes/widgets reutilizables (registra fuentes como side-effect)
from report.generador_pdf import (
    Gauge, ThumbWidget,
    C_BLACK, C_GRAY, C_LGRAY, C_BGRAY, C_RED, C_ORANGE, C_LABEL_BG,
    CONTENT_W, MARGIN, PAGE_W, PAGE_H,
)

# ── Colores adicionales ───────────────────────────────────────────────────────
C_GREEN       = HexColor("#2a9d2a")
C_BLUE_LINE   = HexColor("#1565c0")
C_RED_THRESH  = HexColor("#cc1111")
C_HEADER_BG   = HexColor("#1b4332")
C_ROW_EVEN    = HexColor("#f4f4f4")
C_ROW_WARN    = HexColor("#fff0f0")
C_WARN_TEXT   = HexColor("#cc2222")

MESES_ES = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]

# Definición de los 6 grupos
GRUPOS_MARCA_DK = [
    {"nombre": "Tea Connection (P & A)", "marca": "Tea Connection", "dk": False},
    {"nombre": "Tea Connection (DK)",    "marca": "Tea Connection", "dk": True},
    {"nombre": "Green Eat (P & A)",      "marca": "Green Eat",      "dk": False},
    {"nombre": "Green Eat (DK)",         "marca": "Green Eat",      "dk": True},
    {"nombre": "Las Gracias (P & A)",    "marca": "Las Gracias",    "dk": False},
    {"nombre": "Las Gracias (DK)",       "marca": "Las Gracias",    "dk": True},
]


# ==============================================================================
# Helpers de datos
# ==============================================================================

def _clasificar_dk(tienda_key: str, tiendas: list) -> bool:
    """
    Determina si una clave de tienda ("marca - grupo") pertenece al grupo DK.
    Un grupo se considera DK solo si TODOS sus locales en TIENDAS tienen dk=True.
    Para grupos mixtos (DK y no-DK) → asigna a No DK (conservador).
    """
    if " - " in tienda_key:
        marca_t, grupo_t = tienda_key.split(" - ", 1)
    else:
        marca_t = grupo_t = tienda_key

    matching = [
        t for t in tiendas
        if t.get("marca", "").strip() == marca_t.strip()
        and t.get("grupo", "").strip() == grupo_t.strip()
    ]
    if not matching:
        return False
    return all(t.get("dk", False) for t in matching)


def _get_marca(tienda_key: str) -> str:
    """Extrae la marca de una clave 'marca - grupo'."""
    return tienda_key.split(" - ", 1)[0].strip() if " - " in tienda_key else tienda_key.strip()


# ==============================================================================
# Carga de pedidos desde Google Sheets (una sola vez por ejecución)
# ==============================================================================

def _cargar_pedidos_sheets(mes: int, anio: int) -> list[dict]:
    """
    Descarga el CSV de pedidos de Google Sheets y retorna las filas del
    mes/año indicado. Cada fila es un dict con:
      dia   (int)
      grupo (str)  — grupo físico según TIENDAS
      marca (str)  — marca según TIENDAS
      dk    (bool) — si la tienda es DK según TIENDAS

    El match se hace por el campo 'tienda' del CSV (= columna Codigo de TIENDAS).
    Filas sin match o sin fecha válida se descartan silenciosamente.
    """
    import csv as _csv, io as _io, os as _os, urllib.request as _ur
    from config.locales import TIENDAS

    url = _os.environ.get("PEDIDOS_SHEETS_URL", "").strip().strip("\"'")
    if not url:
        print("PDFs mensuales: PEDIDOS_SHEETS_URL no configurada, sin datos de pedidos.")
        return []

    # Índice (marca_upper, codigo_upper) → (grupo, marca, dk)
    # Se usa la tupla para soportar ubicaciones físicas donde varias marcas
    # comparten el mismo código (ej. "BILGEAAR" = Las Gracias Palermo y
    # Green Eat Billinghurst). La columna 'marca' del CSV desambigua.
    idx: dict[tuple[str, str], tuple[str, str, bool]] = {}
    for t in TIENDAS:
        codigo = (t.get("codigo") or "").strip().upper()
        marca_t = (t.get("marca") or "").strip().upper()
        if codigo and marca_t:
            idx[(marca_t, codigo)] = (t["grupo"], t["marca"], bool(t.get("dk", False)))

    try:
        req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with _ur.urlopen(req, timeout=20) as resp:
            raw = resp.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
    except Exception as exc:
        print(f"PDFs mensuales: no se pudo descargar el CSV de pedidos: {exc}")
        return []

    reader = _csv.DictReader(_io.StringIO(text))
    col_map = {f: f.strip().lower() for f in (reader.fieldnames or [])}
    prefijo = f"{anio}-{mes:02d}-"
    filas = []

    for row in reader:
        rn = {col_map.get(k, k.strip().lower()): v for k, v in row.items()}
        fecha_str = rn.get("dateopen", "").strip()
        if not fecha_str.startswith(prefijo):
            continue
        try:
            dia = int(fecha_str[8:10])
        except (ValueError, IndexError):
            continue
        codigo  = rn.get("tienda", "").strip().upper()
        marca_c = rn.get("marca",  "").strip().upper()
        clave   = (marca_c, codigo)
        if clave not in idx:
            continue
        grupo, marca, dk = idx[clave]
        filas.append({"dia": dia, "grupo": grupo, "marca": marca, "dk": dk})

    print(f"PDFs mensuales: {len(filas)} pedidos cargados desde Sheets para {mes:02d}/{anio}")
    return filas


# ==============================================================================
# Preparación de datos por grupo
# ==============================================================================

def preparar_datos_grupo(marca: str, dk: bool, mes: int, anio: int,
                         historico_data: dict, pedidos_mes: list[dict]) -> dict:
    """
    Combina reclamos del historico.json con pedidos del Google Sheets
    para generar los datos del PDF mensual de un grupo (marca × dk).

    Parámetros:
      marca, dk       — filtros del grupo
      mes, anio       — período
      historico_data  — dict leído del historico.json (clave "reclamos")
      pedidos_mes     — lista de filas pre-cargadas desde Google Sheets
                        (salida de _cargar_pedidos_sheets)

    Retorna dict con claves:
      grupo, marca, dk, mes, anio, mes_num, dias_en_mes,
      total_ordenes, total_reclamos, inac_count, motivos,
      pct_por_dia, locales
    """
    from config.locales import TIENDAS

    prefijo = f"{anio}-{mes:02d}-"

    def _tienda_matches(tienda_key: str) -> bool:
        return (
            _get_marca(tienda_key) == marca
            and _clasificar_dk(tienda_key, TIENDAS) == dk
        )

    # ── Reclamos del mes desde historico.json ─────────────────────────────────
    reclamos_mes = [
        r for r in historico_data.get("reclamos", [])
        if r.get("fecha", "").startswith(prefijo)
        and _tienda_matches(r.get("tienda", ""))
    ]

    total_reclamos = len(reclamos_mes)
    inac_count     = sum(1 for r in reclamos_mes if r.get("es_error_grave") == "SI")

    # ── Motivos ───────────────────────────────────────────────────────────────
    motivos: dict[str, int] = {"INCOMPLETA": 0, "EQUIVOCADA": 0, "CALIDAD": 0}
    for r in reclamos_mes:
        m = (r.get("motivo") or "").upper()
        if "INCOMPLETA" in m or "INCOMPLETO" in m:
            motivos["INCOMPLETA"] += 1
        elif "EQUIVOCADA" in m or "EQUIVOCADO" in m or "WRONG" in m:
            motivos["EQUIVOCADA"] += 1
        elif "CALIDAD" in m or "QUALITY" in m:
            motivos["CALIDAD"] += 1

    # ── Reclamos por día ──────────────────────────────────────────────────────
    dias_en_mes = calendar.monthrange(anio, mes)[1]
    reclamos_por_dia: dict[int, int] = defaultdict(int)
    for r in reclamos_mes:
        try:
            reclamos_por_dia[int(r["fecha"][8:10])] += 1
        except Exception:
            pass

    # ── Pedidos desde Google Sheets filtrados por marca y dk ─────────────────
    pedidos_grupo = [p for p in pedidos_mes if p["marca"] == marca and p["dk"] == dk]

    ordenes_por_dia:  dict[int, int] = defaultdict(int)
    locales_pedidos:  dict[str, int] = defaultdict(int)
    for p in pedidos_grupo:
        ordenes_por_dia[p["dia"]] += 1
        locales_pedidos[p["grupo"]] += 1

    total_ordenes = len(pedidos_grupo)

    # ── % reclamos por día ────────────────────────────────────────────────────
    hoy = datetime.now()
    ultimo_dia_activo = hoy.day if (anio == hoy.year and mes == hoy.month) else dias_en_mes

    pct_por_dia: dict[int, float] = {}
    for dia in range(1, ultimo_dia_activo + 1):
        rec_d = reclamos_por_dia.get(dia, 0)
        ord_d = ordenes_por_dia.get(dia, 0)
        pct_por_dia[dia] = round(rec_d / ord_d * 100, 2) if ord_d > 0 else 0.0

    # ── Por local (grupo físico) ──────────────────────────────────────────────
    locales_reclamos: dict[str, int] = defaultdict(int)
    for r in reclamos_mes:
        tkey = r.get("tienda", "")
        gnom = tkey.split(" - ", 1)[1].strip() if " - " in tkey else tkey
        locales_reclamos[gnom] += 1

    todos_locales = sorted(set(list(locales_pedidos.keys()) + list(locales_reclamos.keys())))
    locales = []
    for nombre in todos_locales:
        ped = locales_pedidos.get(nombre, 0)
        rec = locales_reclamos.get(nombre, 0)
        pct = round(rec / ped * 100, 1) if ped else None
        locales.append({"nombre": nombre, "pedidos": ped, "reclamos": rec, "pct": pct})
    locales.sort(key=lambda x: (-(x["pct"] or 0), x["nombre"]))

    return {
        "grupo":          f"{marca} {'(DK)' if dk else '(P & A)'}",
        "marca":          marca,
        "dk":             dk,
        "mes":            MESES_ES[mes],
        "anio":           anio,
        "mes_num":        mes,
        "dias_en_mes":    dias_en_mes,
        "total_ordenes":  total_ordenes,
        "total_reclamos": total_reclamos,
        "inac_count":     inac_count,
        "motivos":        motivos,
        "pct_por_dia":    pct_por_dia,
        "locales":        locales,
    }


# ==============================================================================
# Flowable: Widget resumen de reclamos (Gauge + breakdown + sello)
# ==============================================================================

class ReclaimosResumenWidget(Flowable):
    """
    3 columnas horizontales:
      Col 1 — Gauge % RECLAMOS / pedidos
      Col 2 — Índices CALIDAD / EQUIVOCADA / INCOMPLETA
      Col 3 — Sello verde/rojo (inaceptables)
    Acepta valores pre-computados (no necesita lista raw de reclamos).
    """
    GW = 155
    GAUGE_CY = 4

    def __init__(self, reclamos_count: int, tot: int, inac_count: int,
                 motivos: dict):
        super().__init__()
        self.reclamos_count = reclamos_count
        self.tot            = tot
        self.inac_count     = inac_count
        self.motivos        = motivos
        self.col_w          = CONTENT_W / 3
        self.width          = CONTENT_W
        self.GAUGE_TY       = 38
        self.COMMON_CY      = self.GAUGE_TY + self.GAUGE_CY
        self.height         = self.GAUGE_TY + self.GAUGE_CY + 62 + 2

    def draw(self):
        c   = self.canv
        gw  = self.GW
        col = self.col_w
        xpad = (col - gw) / 2

        # ── Col 1: Gauge RECLAMOS ─────────────────────────────────────────────
        g = Gauge("RECLAMOS", self.reclamos_count, self.tot, w=gw)
        c.saveState()
        c.translate(xpad, self.GAUGE_TY)
        g.canv = c
        g.draw()
        c.restoreState()

        # ── Col 2: Índices motivos ────────────────────────────────────────────
        n = self.reclamos_count
        cal  = self.motivos.get("CALIDAD",    0)
        eq   = self.motivos.get("EQUIVOCADA", 0)
        inc  = self.motivos.get("INCOMPLETA", 0)
        pct_cal  = round(cal  / n * 100) if n else 0
        pct_eq   = round(eq   / n * 100) if n else 0
        pct_inc  = round(inc  / n * 100) if n else 0

        indices = [
            ("CALIDAD",      pct_cal, cal),
            ("EQUIVOCADO",   pct_eq,  eq),
            ("INCOMPLETO",   pct_inc, inc),
        ]
        ix     = col + 10
        line_h = 22
        total_h = (len(indices) - 1) * line_h
        y_start = self.COMMON_CY + total_h / 2

        for i, (label, pct, cnt) in enumerate(indices):
            y = y_start - i * line_h
            c.setFont("DJB", 9)
            c.setFillColor(C_BLACK)
            c.drawString(ix, y + 4, label)
            c.setFont("DJB", 14)
            c.drawString(ix + 110, y, f"{pct}%")
            if i < len(indices) - 1:
                c.setStrokeColor(C_LGRAY)
                c.setLineWidth(0.4)
                c.line(ix, y - line_h / 2 + 4, ix + 150, y - line_h / 2 + 4)

        # ── Col 3: Sello inaceptables ─────────────────────────────────────────
        t = ThumbWidget(self.inac_count, self.reclamos_count, w=gw,
                        common_cy=self.COMMON_CY, thumb_r=32)
        c.saveState()
        c.translate(2 * col + xpad, 0)
        t.canv = c
        t.draw()
        c.restoreState()


# ==============================================================================
# Flowable: Gráfico de evolución diaria
# ==============================================================================

class LineChartReclamos(Flowable):
    """
    Gráfico de línea: % reclamos por día del mes.
    - Eje X: nro de día (1..31)
    - Eje Y: % reclamos
    - Línea roja discontinua en Y=2% (umbral aceptable)
    """
    UMBRAL_PCT = 2.0

    def __init__(self, pct_por_dia: dict, dias_en_mes: int = 31):
        super().__init__()
        self.datos      = pct_por_dia         # {dia_int: pct_float}
        self.dias_total = dias_en_mes
        self.width      = CONTENT_W
        self.height     = 130                 # altura total del flowable

        # Subárea de dibujo (dentro del flowable)
        self._lx   = 30    # margen izquierdo (etiquetas Y)
        self._by   = 18    # margen inferior (etiquetas X)
        self._rx   = 18    # margen derecho (etiqueta 2%)
        self._ty   = 8     # margen superior

    def _chart_w(self):
        return self.width - self._lx - self._rx

    def _chart_h(self):
        return self.height - self._by - self._ty

    def _to_px(self, dia: int, pct: float, max_pct: float):
        """Convierte (día, %) a coordenadas de canvas."""
        cw = self._chart_w()
        ch = self._chart_h()
        dias = max(self.dias_total - 1, 1)
        px = self._lx + (dia - 1) / dias * cw
        py = self._by + (pct / max_pct) * ch
        return px, py

    def draw(self):
        c  = self.canv
        cw = self._chart_w()
        ch = self._chart_h()

        # Rango Y: mínimo 4% (para que el umbral en 2% quede visible a mitad)
        vals = [v for v in self.datos.values() if v is not None]
        max_val = max(vals, default=0)
        max_pct = max(max_val * 1.25, self.UMBRAL_PCT * 2.5, 5.0)
        # Redondear a entero hacia arriba para ticks limpios
        max_pct = float(int(max_pct) + (1 if max_pct % 1 else 0))

        # ── Grid y etiquetas Y ────────────────────────────────────────────────
        y_ticks = [i for i in range(0, int(max_pct) + 1, 1)]
        for y_val in y_ticks:
            py = self._by + (y_val / max_pct) * ch
            c.setStrokeColor(C_LGRAY)
            c.setLineWidth(0.3)
            c.line(self._lx, py, self._lx + cw, py)
            c.setFont("DJ", 6.5)
            c.setFillColor(C_GRAY)
            c.drawRightString(self._lx - 3, py - 2.5, f"{y_val}%")

        # ── Etiquetas eje X (días) ─────────────────────────────────────────────
        c.setFont("DJ", 6.5)
        c.setFillColor(C_GRAY)
        step = 5 if self.dias_total > 20 else 3
        for dia in range(1, self.dias_total + 1):
            if dia == 1 or dia % step == 0 or dia == self.dias_total:
                px, _ = self._to_px(dia, 0, max_pct)
                c.drawCentredString(px, self._by - 11, str(dia))

        # ── Línea umbral 2% ───────────────────────────────────────────────────
        py_umbral = self._by + (self.UMBRAL_PCT / max_pct) * ch
        c.setStrokeColor(C_RED_THRESH)
        c.setLineWidth(0.9)
        c.setDash([5, 3])
        c.line(self._lx, py_umbral, self._lx + cw, py_umbral)
        c.setDash([])
        c.setFillColor(C_RED_THRESH)
        c.setFont("DJB", 7)
        c.drawString(self._lx + cw + 3, py_umbral - 2.5, "2%")

        # ── Línea de datos ────────────────────────────────────────────────────
        puntos = []
        for dia in sorted(self.datos.keys()):
            val = self.datos[dia]
            if val is not None:
                px, py = self._to_px(dia, val, max_pct)
                puntos.append((px, py))

        if len(puntos) >= 2:
            c.setStrokeColor(C_BLUE_LINE)
            c.setLineWidth(1.6)
            path = c.beginPath()
            path.moveTo(*puntos[0])
            for p in puntos[1:]:
                path.lineTo(*p)
            c.drawPath(path, stroke=1, fill=0)

        # Puntos individuales
        for px, py in puntos:
            c.setFillColor(C_BLUE_LINE)
            c.setStrokeColor(white)
            c.setLineWidth(0.8)
            c.circle(px, py, 2.2, fill=1, stroke=1)

        # Sin datos → mensaje
        if not puntos:
            c.setFont("DJI", 9)
            c.setFillColor(C_GRAY)
            c.drawCentredString(self._lx + cw / 2,
                                self._by + ch / 2, "Sin datos para el período")

        # ── Borde del área ────────────────────────────────────────────────────
        c.setStrokeColor(C_LGRAY)
        c.setLineWidth(0.5)
        c.rect(self._lx, self._by, cw, ch, stroke=1, fill=0)


# ==============================================================================
# Tabla de locales
# ==============================================================================

def _tabla_locales(locales: list) -> Table:
    """
    Construye la tabla LOCAL | Q. PEDIDOS | Q. RECLAMOS | % RECLAMOS.
    Filas con % > 2% se resaltan en rojo suave.
    """
    col_w = [CONTENT_W * 0.52, CONTENT_W * 0.16, CONTENT_W * 0.16, CONTENT_W * 0.16]

    # Encabezado
    header = ["LOCAL", "Q. PEDIDOS", "Q. RECLAMOS", "% RECLAMOS"]

    rows = [header]
    for loc in locales:
        pct_str = f"{loc['pct']:.1f}%" if loc["pct"] is not None else "—"
        rows.append([
            loc["nombre"],
            f"{loc['pedidos']:,}".replace(",", "."),
            str(loc["reclamos"]),
            pct_str,
        ])

    # Totales
    total_ped = sum(l["pedidos"] for l in locales)
    total_rec = sum(l["reclamos"] for l in locales)
    total_pct = round(total_rec / total_ped * 100, 1) if total_ped else None
    total_pct_str = f"{total_pct:.1f}%" if total_pct is not None else "—"
    rows.append([
        "TOTAL",
        f"{total_ped:,}".replace(",", "."),
        str(total_rec),
        total_pct_str,
    ])

    tbl = Table(rows, colWidths=col_w, repeatRows=1)

    n_data = len(locales)

    style_cmds = [
        # ── Encabezado ──────────────────────────────────────────────────────
        ("BACKGROUND",    (0, 0), (-1, 0),        HexColor("#1b4332")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),        white),
        ("FONTNAME",      (0, 0), (-1, 0),        "DJB"),
        ("FONTSIZE",      (0, 0), (-1, 0),        8),
        ("ALIGN",         (0, 0), (-1, 0),        "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, 0),        5),
        ("BOTTOMPADDING", (0, 0), (-1, 0),        5),

        # ── Datos: estilo base ───────────────────────────────────────────────
        ("FONTNAME",      (0, 1), (-1, -2),       "DJ"),
        ("FONTSIZE",      (0, 1), (-1, -2),       8.5),
        ("TOPPADDING",    (0, 1), (-1, -2),       4),
        ("BOTTOMPADDING", (0, 1), (-1, -2),       4),
        ("ALIGN",         (1, 1), (-1, -2),       "CENTER"),
        ("ALIGN",         (0, 1), (0, -2),        "LEFT"),

        # ── Fila TOTAL ───────────────────────────────────────────────────────
        ("FONTNAME",      (0, -1), (-1, -1),      "DJB"),
        ("FONTSIZE",      (0, -1), (-1, -1),      8.5),
        ("BACKGROUND",    (0, -1), (-1, -1),      HexColor("#e8f5e9")),
        ("ALIGN",         (0, -1), (-1, -1),      "CENTER"),
        ("TOPPADDING",    (0, -1), (-1, -1),       5),
        ("BOTTOMPADDING", (0, -1), (-1, -1),       5),

        # ── Bordes ──────────────────────────────────────────────────────────
        ("GRID",          (0, 0),  (-1, -1),      0.35, HexColor("#cccccc")),
        ("LINEBELOW",     (0, 0),  (-1, 0),       1.0, HexColor("#1b4332")),
        ("LINEABOVE",     (0, -1), (-1, -1),      1.0, HexColor("#888888")),
    ]

    # Filas alternas + highlight pct > 2%
    for i, loc in enumerate(locales, start=1):
        row_y = i
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, row_y), (-1, row_y), C_ROW_EVEN))
        pct_val = loc.get("pct")
        if pct_val is not None and pct_val > 2.0:
            style_cmds.append(("TEXTCOLOR", (3, row_y), (3, row_y), C_WARN_TEXT))
            style_cmds.append(("FONTNAME",  (3, row_y), (3, row_y), "DJB"))

    tbl.setStyle(TableStyle(style_cmds))
    return tbl


# ==============================================================================
# Header / Footer del PDF mensual
# ==============================================================================

class HeaderFooterMensual:
    """Dibuja encabezado y número de página en cada hoja."""

    def __init__(self, data: dict, tpr: list):
        self.data = data
        self.tpr  = tpr

    def __call__(self, canvas, doc):
        canvas.saveState()
        w, h = A4
        y = h - 12 * mm

        # Nombre del grupo (izquierda)
        canvas.setFont("DJB", 13)
        canvas.setFillColor(C_BLACK)
        canvas.drawString(MARGIN, y, self.data["grupo"].upper())

        # Mes + año (centro)
        canvas.setFont("DJB", 11)
        canvas.setFillColor(C_GRAY)
        mes_label = f"{self.data['mes'].upper()} {self.data['anio']}"
        canvas.drawCentredString(w / 2, y, mes_label)

        # Total pedidos (derecha)
        canvas.setFont("DJ", 9)
        canvas.setFillColor(C_BLACK)
        tot = self.data.get("total_ordenes", 0)
        canvas.drawRightString(w - MARGIN, y, f"Total pedidos: {tot:,}".replace(",", "."))

        # Línea separadora
        canvas.setStrokeColor(C_LGRAY)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, h - 14.5 * mm, w - MARGIN, h - 14.5 * mm)

        canvas.restoreState()


# ==============================================================================
# Construcción del story
# ==============================================================================

def _make_styles():
    return {
        "sec": ParagraphStyle(
            "sec_m", fontName="DJB", fontSize=11, textColor=C_BLACK,
            leading=16, spaceBefore=0, spaceAfter=0,
            backColor=HexColor("#EFEFED"), leftIndent=6,
        ),
        "sin_datos": ParagraphStyle(
            "sin_m", fontName="DJ", fontSize=10, textColor=C_GRAY,
            leading=14, leftIndent=8,
        ),
        "badge_dk": ParagraphStyle(
            "bdk", fontName="DJB", fontSize=9, textColor=white,
            leading=13, backColor=HexColor("#1565c0"), leftIndent=6,
        ),
    }


def build_story_mensual(data: dict) -> list:
    styles = _make_styles()
    story  = []

    total_reclamos = data["total_reclamos"]
    total_ordenes  = data["total_ordenes"]
    inac_count     = data["inac_count"]
    motivos        = data["motivos"]
    pct_por_dia    = data["pct_por_dia"]
    locales        = data["locales"]
    dias_en_mes    = data["dias_en_mes"]


    # ── SECCIÓN: Resumen de reclamos ──────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=1.0, color=C_LGRAY, spaceAfter=3 * mm))

    if total_ordenes > 0:
        story.append(ReclaimosResumenWidget(
            reclamos_count=total_reclamos,
            tot=total_ordenes,
            inac_count=inac_count,
            motivos=motivos,
        ))
    else:
        story.append(Paragraph("Sin datos de pedidos para este período.", styles["sin_datos"]))

    story.append(Spacer(1, 4 * mm))

    # ── SECCIÓN: Evolución diaria ──────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LGRAY))
    story.append(Paragraph("EVOLUCIÓN DIARIA DE % RECLAMOS", styles["sec"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LGRAY, spaceAfter=3 * mm))

    story.append(LineChartReclamos(pct_por_dia, dias_en_mes))
    story.append(Spacer(1, 4 * mm))

    # ── SECCIÓN: Tabla por local ───────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LGRAY))
    story.append(Paragraph("DETALLE POR LOCAL", styles["sec"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LGRAY, spaceAfter=3 * mm))

    if locales:
        story.append(_tabla_locales(locales))
    else:
        story.append(Paragraph("Sin locales con datos para este período.", styles["sin_datos"]))

    story.append(Spacer(1, 4 * mm))

    return story


# ==============================================================================
# Función principal de generación
# ==============================================================================

def build_report_mensual(data: dict, out_path: str) -> None:
    """Genera el PDF mensual para un grupo en out_path."""
    from pypdf import PdfReader

    tpr = [1]
    cb  = HeaderFooterMensual(data, tpr)

    def make_doc(fp):
        return SimpleDocTemplate(
            fp, pagesize=A4,
            leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=18 * mm, bottomMargin=14 * mm,
        )

    # Primer pasada: contar páginas
    buf = io.BytesIO()
    make_doc(buf).build(build_story_mensual(data), onFirstPage=cb, onLaterPages=cb)
    buf.seek(0)
    tpr[0] = len(PdfReader(buf).pages)

    # Segunda pasada: generar con total de páginas correcto
    make_doc(out_path).build(build_story_mensual(data), onFirstPage=cb, onLaterPages=cb)
    print(f"OK — {out_path}  ({tpr[0]} páginas)")


def generar_pdfs_mensuales(output_dir: str, anio: int = None, mes: int = None) -> list:
    """
    Lee el historico.json (reclamos) y el Google Sheets de pedidos,
    filtra por mes/año, y genera los 6 PDFs mensuales.

    Parámetros:
      output_dir  — carpeta donde se guardan los PDFs
      anio, mes   — año y mes a procesar (default: mes en curso)

    Retorna lista de rutas de PDFs generados.
    """
    from config.historico import leer_historico

    hoy = datetime.now()
    if anio is None:
        anio = hoy.year
    if mes is None:
        mes = hoy.month

    # ── Reclamos desde historico.json ─────────────────────────────────────────
    historico = leer_historico()
    if not historico.get("reclamos"):
        print("PDFs mensuales: no hay reclamos en el histórico — omitiendo")
        return []

    # ── Pedidos desde Google Sheets (descarga única para los 6 PDFs) ─────────
    pedidos_mes = _cargar_pedidos_sheets(mes, anio)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    generados = []

    for grupo in GRUPOS_MARCA_DK:
        marca  = grupo["marca"]
        dk     = grupo["dk"]
        nombre = grupo["nombre"]

        try:
            data = preparar_datos_grupo(marca, dk, mes, anio, historico, pedidos_mes)

            nombre_archivo = nombre.replace(" ", "_") + f"_{anio}-{mes:02d}.pdf"
            ruta_pdf = output_path / nombre_archivo

            build_report_mensual(data, str(ruta_pdf))
            generados.append(ruta_pdf)

        except Exception as e:
            import traceback
            print(f"  Error generando PDF mensual para {nombre!r}: {e}")
            traceback.print_exc()

    return generados
