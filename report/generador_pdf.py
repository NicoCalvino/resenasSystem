"""
Informe de reseñas negativas v4.
Cambios respecto a versión anterior:
- Gauges separados del encabezado (no se superponen)
- Estrellas primero, más grandes (★★★★★ de 5), luego fecha y orden
- Marca y app alineadas a la derecha como info secundaria
- Órdenes agrupadas (todos los platos de la misma orden juntos)
- Tags y comentarios más grandes y destacados
"""
import io
import os
from math import cos, sin, radians
from collections import OrderedDict

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    KeepTogether, Flowable, Table, TableStyle
)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── FUENTES ───────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
font_path_uno = os.path.join(BASE_DIR, 'fonts', 'DejaVuSans.ttf')
font_path_dos = os.path.join(BASE_DIR, 'fonts', 'DejaVuSans-Bold.ttf')
font_path_tres = os.path.join(BASE_DIR, 'fonts', 'DejaVuSans-Oblique.ttf')
# _FD = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("DJ",   font_path_uno))
pdfmetrics.registerFont(TTFont("DJB",  font_path_dos))
pdfmetrics.registerFont(TTFont("DJI",  font_path_tres))
pdfmetrics.registerFontFamily("DejaVu", normal="DJ", bold="DJB", italic="DJI")

STAR_FULL  = "\u2605"
STAR_EMPTY = "\u2606"

# ── COLORES ───────────────────────────────────────────────────────────────────
C_BLACK    = HexColor("#1a1a1a")
C_GRAY     = HexColor("#888888")
C_LGRAY    = HexColor("#e0e0e0")
C_BGRAY    = HexColor("#c8c8c8")
C_RED      = HexColor("#cc2222")
C_RED_L    = HexColor("#fff5f5")
C_RED_M    = HexColor("#f5c0c0")
C_ORANGE   = HexColor("#d07000")
C_LABEL_BG = HexColor("#eeeeee")

# 3 segmentos: verde (0-2%), amarillo (2.1-3%), rojo (>3%)
# Fracciones del arco de 180°: verde=50%, amarillo=16.7%, rojo=33.3%
GAUGE_SEGMENTS = [
    {"color": "#2a9d2a", "frac": 1/3},
    {"color": "#f0e020", "frac": 1/3},
    {"color": "#cc1111", "frac": 1/3},
]

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

# ── ESTILOS ───────────────────────────────────────────────────────────────────
def make_styles():
    return {
        # encabezado de orden: estrellas grandes
        "stars": ParagraphStyle("stars", fontName="DJB", fontSize=16,
                 textColor=C_ORANGE, leading=20),
        # fecha + orden
        "order_meta": ParagraphStyle("ometa", fontName="DJ", fontSize=10,
                      textColor=C_GRAY, leading=14),
        # marca + app (derecha, pequeño)
        "brand_right": ParagraphStyle("br", fontName="DJ", fontSize=8.5,
                       textColor=C_GRAY, leading=12, alignment=TA_RIGHT),
        # nombre del plato
        "dish": ParagraphStyle("dish", fontName="DJ", fontSize=10,
                textColor=C_BLACK, leading=14, leftIndent=8),
        # etiqueta de comentario rápido — MÁS GRANDE
        "tag": ParagraphStyle("tag", fontName="DJB", fontSize=11,
               textColor=C_GRAY, leading=15, leftIndent=8),
        "tag_g": ParagraphStyle("tag_g", fontName="DJB", fontSize=11,
                 textColor=C_RED, leading=15, leftIndent=8),
        # comentario escrito — MÁS GRANDE
        "comment": ParagraphStyle("cmt", fontName="DJI", fontSize=11,
                   textColor=C_BLACK, leading=15, leftIndent=8),
    }

# ── FLOWABLE: VELOCÍMETRO ─────────────────────────────────────────────────────
class Gauge(Flowable):
    R_OUT  = 62
    R_IN   = 38
    R_HUB  = 5
    NEEDLE = 54

    def __init__(self, label, num, den, w=175):
        super().__init__()
        self.label  = label
        self.num    = num
        self.den    = den
        self.pct    = round(num / den * 100) if den else 0
        self.width  = w
        self.height = self.R_OUT + 10

    def _segment(self, c, cx, cy, r_out, r_in, a_start, a_end, color):
        path = c.beginPath()
        path.moveTo(cx + r_out * cos(radians(a_start)),
                    cy + r_out * sin(radians(a_start)))
        path.arcTo(cx-r_out, cy-r_out, cx+r_out, cy+r_out,
                   a_start, a_end - a_start)
        path.lineTo(cx + r_in * cos(radians(a_end)),
                    cy + r_in * sin(radians(a_end)))
        path.arcTo(cx-r_in, cy-r_in, cx+r_in, cy+r_in,
                   a_end, a_start - a_end)
        path.close()
        c.setFillColor(HexColor(color))
        c.setStrokeColor(white)
        c.setLineWidth(1.8)
        c.drawPath(path, fill=1, stroke=1)

    def _needle_angle(self):
        # Arco dividido en 3 tercios iguales de 60° cada uno:
        # verde:    180°→120°  (0–2%)   → centro: 150°
        # amarillo: 120°→60°   (2.1–3%) → centro: 90°
        # rojo:      60°→0°   (>3%)     → centro: 30°
        pct = self.pct
        if pct <= 2:
            return 150
        elif pct <= 3:
            return 90
        else:
            return 30

    def draw(self):
        c  = self.canv
        cx = self.width / 2
        cy = 4

        # 3 segmentos
        a_cursor = 180.0
        for seg in GAUGE_SEGMENTS:
            sweep  = seg["frac"] * 180.0
            a_end  = a_cursor - sweep
            self._segment(c, cx, cy, self.R_OUT, self.R_IN, a_cursor, a_end, seg["color"])
            a_cursor = a_end

        # Semicírculo gris interior
        r = self.R_IN - 1
        c.setFillColor(C_BGRAY)
        c.setStrokeColor(C_BGRAY)
        c.setLineWidth(0)
        path = c.beginPath()
        path.moveTo(cx - r, cy)
        path.arcTo(cx - r, cy - r, cx + r, cy + r, 180, -180)
        path.lineTo(cx - r, cy)
        path.close()
        c.drawPath(path, fill=1, stroke=0)

        # Aguja según umbrales
        needle_angle = radians(self._needle_angle())
        nx = cx + self.NEEDLE * cos(needle_angle)
        ny = cy + self.NEEDLE * sin(needle_angle)
        c.setStrokeColor(black)
        c.setLineWidth(2.2)
        c.line(cx, cy, nx, ny)

        c.setFillColor(black)
        c.setStrokeColor(white)
        c.setLineWidth(0.8)
        c.circle(cx, cy, self.R_HUB, fill=1, stroke=1)

        # Leyenda: caja angosta centrada, título + % | CANTIDAD
        lh = 28
        lw = 130          # más angosto que el gauge (era self.width = 175)
        lx = cx - lw / 2  # centrado bajo el arco
        ly = -(lh + 4)
        c.setFillColor(C_LABEL_BG)
        c.setStrokeColor(C_LGRAY)
        c.setLineWidth(0.6)
        c.roundRect(lx, ly, lw, lh, 3, fill=1, stroke=1)
        c.setFillColor(C_BLACK)
        c.setFont("DJB", 8)
        c.drawCentredString(cx, ly + lh - 8, f"{self.label}  %{self.pct}")
        c.setFont("DJ", 7.5)
        c.drawCentredString(cx, ly + 7, f"CANTIDAD: {self.num}")


# ── FLOWABLE: GAUGE ÚNICO CENTRADO (para Reclamos) ───────────────────────────
class GaugeSingle(Flowable):
    def __init__(self, label, num, den):
        super().__init__()
        self.label  = label
        self.num    = num
        self.den    = den
        self.gw     = 175
        self.width  = CONTENT_W
        self.TRANSLATE_Y = 38
        self.height = self.TRANSLATE_Y + 4 + 62 + 2

    def draw(self):
        c  = self.canv
        g  = Gauge(self.label, self.num, self.den, w=self.gw)
        c.saveState()
        c.translate(0, self.TRANSLATE_Y)
        g.canv = c
        g.draw()
        c.restoreState()



class GaugePair(Flowable):
    # Dimensiones compartidas para alinear gauge y thumb
    GW       = 175   # ancho de cada widget
    GAUGE_CY = 4     # cy del gauge (coordenada base en su espacio local)
    THUMB_R  = 46    # radio del círculo del thumb
    # El thumb tiene su centro a THUMB_R + margen desde su base local
    THUMB_CY_LOCAL = THUMB_R + 4   # cy del thumb en su espacio local

    def __init__(self, neg, tot, grav):
        super().__init__()
        self.neg   = neg
        self.tot   = tot
        self.grav  = grav
        self.width  = CONTENT_W
        # En ReportLab el canvas del flowable tiene y=0 en la BASE y crece hacia arriba.
        # El gauge dibuja: arco sube R_OUT=62 sobre cy, leyenda baja (lh+4)=32 bajo cy.
        # cy del gauge en su espacio local = 4 (constante en Gauge.draw).
        # Para que el arco no salga por arriba: translate_y + cy + R_OUT <= self.height
        # Elegimos translate_y = R_OUT + lh + 4 + 2 = 62 + 32 + 2 = 96 → todo dentro
        # TRANSLATE_Y = distancia desde base del flowable hasta cy del gauge
        # Mínimo necesario: leyenda baja (lh+4)=32 bajo cy, cy del gauge local=4
        # → mínimo = 32 + 4 + 2 = 38pt para que la leyenda no se corte
        self.GAUGE_TRANSLATE_Y = 38
        self.COMMON_CY = self.GAUGE_TRANSLATE_Y + self.GAUGE_CY
        self.height = self.GAUGE_TRANSLATE_Y + self.GAUGE_CY + 62 + 2

    def draw(self):
        c   = self.canv
        gw  = self.GW
        gap = (self.width - 2 * gw) / 2
        x1  = gap / 2
        x2  = x1 + gw + gap

        # Gauge izquierda
        g = Gauge("1 Y 2 ESTRELLAS", self.neg, self.tot, w=gw)
        c.saveState()
        c.translate(x1, self.GAUGE_TRANSLATE_Y)
        g.canv = c
        g.draw()
        c.restoreState()

        # Thumb derecha — su common_cy en espacio global = COMMON_CY
        t = ThumbWidget(self.grav, self.neg, w=gw,
                        common_cy=self.COMMON_CY,
                        thumb_r=self.THUMB_R)
        c.saveState()
        c.translate(x2, 0)
        t.canv = c
        t.draw()
        c.restoreState()


# ── FLOWABLE: PULGAR (INACEPTABLES) ──────────────────────────────────────────
class ThumbWidget(Flowable):
    """Círculo verde (ok) o rojo (error) con símbolo claro adentro."""

    def __init__(self, num, den, w=175, common_cy=70, thumb_r=46):
        super().__init__()
        self.num       = num
        self.den       = den
        self.pct       = round(num / den * 100) if den else 0
        self.ok        = (num == 0)
        self.width     = w
        self.common_cy = common_cy
        self.R         = thumb_r
        self.height    = common_cy + thumb_r + 10

    def draw(self):
        c   = self.canv
        cx  = self.width / 2

        # El círculo debe quedar claramente ARRIBA de la leyenda.
        # Leyenda: ly = cy - (lh+4) - 4, lh=28  → tope inferior del círculo = cy - R
        # Para que no se solapen: cy - R > ly + lh  → cy > ly + lh + R
        # Calculamos cy a partir de common_cy (centro compartido con el gauge)
        # pero lo subimos para que el círculo quede bien por encima de la caja
        lh = 28
        R   = 32   # círculo más chico (era 46)
        Rin = R - 6
        # Posición de la leyenda fija (igual que Gauge): base en common_cy - (lh+4) - 4
        ly  = self.common_cy - (lh + 4) - 4
        # Centro del círculo: separado del tope de la caja por al menos 6px
        cy  = ly + lh + R + 6

        # Aro gris
        c.setFillColor(HexColor("#aaaaaa"))
        c.setStrokeColor(white)
        c.setLineWidth(0)
        c.circle(cx, cy, R, fill=1, stroke=0)

        # Círculo de color
        color = HexColor("#2a9d2a") if self.ok else HexColor("#cc1111")
        c.setFillColor(color)
        c.circle(cx, cy, Rin, fill=1, stroke=0)

        # Símbolo: más pequeño y centrado en el círculo
        c.setFillColor(white)
        symbol = "\u2713" if self.ok else "\u2717"
        c.setFont("DJB", 30)
        c.drawCentredString(cx, cy - 9, symbol)

        # Leyenda — misma caja que el Gauge
        lw = 130
        lx = cx - lw / 2
        c.setFillColor(C_LABEL_BG)
        c.setStrokeColor(C_LGRAY)
        c.setLineWidth(0.6)
        c.roundRect(lx, ly, lw, lh, 3, fill=1, stroke=1)
        c.setFillColor(C_BLACK)
        c.setFont("DJB", 8)
        c.drawCentredString(cx, ly + lh - 8, f"INACEPTABLES  %{self.pct}")
        c.setFont("DJ", 7.5)
        c.drawCentredString(cx, ly + 7, f"CANTIDAD: {self.num}")


class GraveBadge(Flowable):
    def __init__(self):
        super().__init__()
        self.width  = 120
        self.height = 18

    def draw(self):
        c = self.canv
        c.setFillColor(C_RED)
        c.roundRect(0, 1, 116, 15, 4, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("DJB", 8.5)
        c.drawCentredString(58, 5.5, "\u26a0  ERROR GRAVE")


# ── HELPERS ───────────────────────────────────────────────────────────────────
def group_by_order(resenas):
    """Agrupa los platos de la misma orden en un solo bloque."""
    groups = OrderedDict()
    for rev in resenas:
        key = rev["orden"]
        if key not in groups:
            groups[key] = {
                "fecha":    rev["fecha"],
                "orden":    rev["orden"],
                "marca":    rev["marca"],
                "app":      rev["app"],
                "estrellas":rev["estrellas"],
                "platos":   [],
            }
        groups[key]["platos"].extend(rev["platos"])
    return list(groups.values())


# ── FLOWABLE: GAUGE + ÍNDICES DE RECLAMOS ─────────────────────────────────────
class ReclaimosGaugeWidget(Flowable):
    """Gauge de reclamos a la izquierda + índices CALIDAD/EQUIVOCADOS/INCOMPLETOS a la derecha."""

    MOTIVO_CALIDAD     = "NO LLEGÓ EN BUENAS CONDICIONES"
    MOTIVO_EQUIVOCADO  = "INCORRECTO O DIFERENTE A LO ESPERADO"
    MOTIVO_INCOMPLETO  = "INCOMPLETO"

    def __init__(self, reclamos, tot):
        super().__init__()
        self.reclamos = reclamos
        self.tot      = tot
        self.gw       = 175
        self.width    = CONTENT_W
        self.TRANSLATE_Y = 38
        self.height   = self.TRANSLATE_Y + 4 + 62 + 2

    def _contar(self):
        n = len(self.reclamos)
        cal = eq = inc = 0
        for r in self.reclamos:
            razon = (r.get("razon") or "").upper()
            if self.MOTIVO_CALIDAD.upper()    in razon: cal += 1
            if self.MOTIVO_EQUIVOCADO.upper() in razon: eq  += 1
            if self.MOTIVO_INCOMPLETO.upper() in razon: inc += 1
        return n, cal, eq, inc

    def draw(self):
        c = self.canv
        n, cal, eq, inc = self._contar()

        # ── Gauge izquierda ──
        g = Gauge("RECLAMOS", n, self.tot, w=self.gw)
        c.saveState()
        c.translate(0, self.TRANSLATE_Y)
        g.canv = c
        g.draw()
        c.restoreState()

        # ── Índices derecha ──
        # Posición X: a la derecha del gauge con un gap
        ix = self.gw + 130
        # Centro vertical: alineado con el centro del gauge
        gauge_cy = self.TRANSLATE_Y + 4   # cy del gauge en espacio global
        line_h   = 22                      # separación entre líneas

        pct_cal = round(cal / n * 100) if n else 0
        pct_eq  = round(eq  / n * 100) if n else 0
        pct_inc = round(inc / n * 100) if n else 0

        indices = [
            ("CALIDAD",      pct_cal, cal),
            ("EQUIVOCADOS",  pct_eq,  eq),
            ("INCOMPLETOS",  pct_inc, inc),
        ]

        total_h = (len(indices) - 1) * line_h
        y_start = gauge_cy + total_h / 2

        for i, (label, pct, cnt) in enumerate(indices):
            y = y_start - i * line_h

            # Etiqueta
            c.setFont("DJB", 9)
            c.setFillColor(C_BLACK)
            c.drawString(ix, y + 4, label)

            # Porcentaje destacado
            c.setFont("DJB", 14)
            c.setFillColor(C_BLACK)
            val_str = f"%{pct}"
            c.drawString(ix + 110, y, val_str)

            # Línea separadora sutil — solo bajo el bloque de texto
            if i < len(indices) - 1:
                c.setStrokeColor(C_LGRAY)
                c.setLineWidth(0.4)
                c.line(ix, y - line_h / 2 + 4, ix + 150, y - line_h / 2 + 4)



def build_story(data, styles, tpr):
    neg      = data["resenas_negativas"]
    tot      = data["total_ordenes"]
    grav     = data["errores_graves"]
    reclamos = data.get("reclamos", [])
    story = []

    from reportlab.lib.styles import ParagraphStyle as _PS
    _sec = _PS("sec", fontName="DJB", fontSize=15, textColor=C_BLACK,
               leading=22, spaceBefore=0, spaceAfter=0,
               backColor=HexColor("#EFEFED"), leftIndent=8)

    # ── TÍTULO RESEÑAS primero, luego los gráficos ──
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LGRAY, spaceAfter=0))
    story.append(Paragraph("RESEÑAS", _sec))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LGRAY, spaceAfter=2 * mm))
    story.append(GaugePair(neg, tot, grav))
    story.append(Spacer(1, 1 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LGRAY, spaceAfter=2 * mm))

    resenas_ord = sorted(
        data["resenas"],
        key=lambda r: (r["fecha"][:10], r["marca"], r["fecha"][11:] if len(r["fecha"]) > 10 else "")
    )
    grupos = group_by_order(resenas_ord)

    for grupo in grupos:
        any_grave = any(p.get("grave") for p in grupo["platos"])
        block = []

        # ── ENCABEZADO DE ORDEN ──────────────────────────────────────────────
        # fila: estrellas (izq) | marca + app (der)
        n = grupo["estrellas"]
        stars_str = STAR_FULL * n + STAR_EMPTY * (5 - n)

        brand_app = f'{grupo["marca"]}  ·  {grupo["app"]}'

        # Tabla de 2 columnas: estrellas | marca+app
        tbl = Table(
            [[
                Paragraph(stars_str, styles["stars"]),
                Paragraph(brand_app, styles["brand_right"]),
            ]],
            colWidths=[CONTENT_W * 0.55, CONTENT_W * 0.45],
            hAlign="LEFT",
        )
        tbl.setStyle(TableStyle([
            ("VALIGN",    (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
        ]))
        block.append(tbl)

        # fecha + hora + nro de orden
        block.append(Paragraph(
            f'<font name="DJB" color="#1a1a1a">{grupo["fecha"]}</font>'
            f'   <font name="DJ" color="#888888">Orden: {grupo["orden"]}</font>',
            styles["order_meta"]
        ))

        block.append(Spacer(1, 1.5 * mm))

        # ── PLATOS ──────────────────────────────────────────────────────────
        for idx, plato in enumerate(grupo["platos"]):
            grave = plato.get("grave", False)

            # separador sutil entre platos (no en el primero)
            if idx > 0:
                block.append(Spacer(1, 1*mm))
                block.append(HRFlowable(width="88%", thickness=0.3,
                                         color=HexColor("#CCCCCC"),
                                         dash=[2,3], spaceAfter=2*mm))

            block.append(Paragraph(plato["nombre"], styles["dish"]))

            # badge ERROR GRAVE junto al plato que lo tiene
            if grave:
                block.append(Spacer(1, 1 * mm))
                block.append(GraveBadge())
                block.append(Spacer(1, 1 * mm))

            for tag in plato["tags"]:
                s = styles["tag_g"] if grave else styles["tag"]
                block.append(Paragraph(tag, s))

            txt = plato["comentario"] if plato["comentario"] else ""
            block.append(Paragraph(f'"{txt}"', styles["comment"]))

        # separador principal entre órdenes
        block.append(Spacer(1, 2.5 * mm))
        sep_color = C_RED_M if any_grave else HexColor("#AAAAAA")
        block.append(HRFlowable(width="100%", thickness=1.2,
                                 color=sep_color, spaceAfter=3.5 * mm))
        story.append(KeepTogether(block))

    # ── SECCIÓN RECLAMOS ──────────────────────────────────────────────────────
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LGRAY, spaceAfter=0))

    _sec_r = _PS("secr", fontName="DJB", fontSize=15, textColor=C_BLACK,
                 leading=22, spaceBefore=5, spaceAfter=5,
                 backColor=HexColor("#FFF3E0"), leftIndent=8)
    _titulo_reclamos = f"RECLAMOS  ({len(reclamos)})" if reclamos else "RECLAMOS"
    story.append(Paragraph(_titulo_reclamos, _sec_r))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LGRAY, spaceAfter=2 * mm))

    # Gauge + índices de reclamos
    story.append(ReclaimosGaugeWidget(reclamos, tot))
    story.append(Spacer(1, 1 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LGRAY, spaceAfter=4 * mm))

    if not reclamos:
        _style_sin = _PS("sinrec", fontName="DJI", fontSize=10,
                         textColor=C_GRAY, leading=14, leftIndent=8)
        story.append(Paragraph("Sin reclamos en el período.", _style_sin))
        story.append(Spacer(1, 4 * mm))
    else:
        # Estilos específicos para reclamos
        _style_platos_ped = _PS("platosped", fontName="DJ", fontSize=9,
                                textColor=HexColor("#555555"), leading=13, leftIndent=8)
        _style_platos_rec = _PS("platosrec", fontName="DJB", fontSize=10,
                                textColor=HexColor("#C05800"), leading=14, leftIndent=8)
        _style_razon      = _PS("razon", fontName="DJB", fontSize=9,
                                textColor=HexColor("#444444"), leading=13, leftIndent=8)
        _style_meta_rec   = _PS("metarec", fontName="DJ", fontSize=10,
                                textColor=C_GRAY, leading=14)

        reclamos_ord = sorted(reclamos, key=lambda r: (r["fecha"][:10], r["fecha"][11:] if len(r["fecha"]) > 10 else ""))

        for rc in reclamos_ord:
            block = []

            # Encabezado: fecha + orden | marca (derecha)
            tbl = Table(
                [[
                    Paragraph(
                        f'<font name="DJB" color="#1a1a1a">{rc["fecha"]}</font>'
                        f'   <font name="DJ" color="#888888">Orden: {rc["orden"]}</font>',
                        _style_meta_rec
                    ),
                    Paragraph(rc["marca"] + "  ·  " + rc.get("app", ""), styles["brand_right"]),
                ]],
                colWidths=[CONTENT_W * 0.60, CONTENT_W * 0.40],
                hAlign="LEFT",
            )
            tbl.setStyle(TableStyle([
                ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING",  (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING",   (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
            ]))
            block.append(tbl)
            block.append(Spacer(1, 1.5 * mm))

            # Platos pedidos (todos los de la orden)
            if rc.get("platos_pedidos"):
                block.append(Paragraph(
                    f'<font name="DJB">Pedido:</font>  {rc["platos_pedidos"]}',
                    _style_platos_ped
                ))

            # Platos reclamados (destacados en naranja)
            if rc.get("platos_reclamados"):
                block.append(Spacer(1, 1 * mm))
                block.append(Paragraph(
                    f'<font name="DJB">Reclamado:</font>  {rc["platos_reclamados"]}',
                    _style_platos_rec
                ))

            # Motivo
            if rc.get("razon"):
                block.append(Spacer(1, 1 * mm))
                block.append(Paragraph(
                    f'<font name="DJB">Motivo:</font>  {rc["razon"]}',
                    _style_razon
                ))

            # Comentario del cliente
            if rc.get("comentario"):
                block.append(Spacer(1, 1 * mm))
                block.append(Paragraph(
                    f'<font name="DJB">Comentario:</font>  {rc["comentario"]}',
                    styles["comment"]
                ))

            block.append(Spacer(1, 2.5 * mm))
            block.append(HRFlowable(width="100%", thickness=0.8,
                                     color=HexColor("#FFCC88"), spaceAfter=3.5 * mm))
            story.append(KeepTogether(block))

    return story


# ── HEADER / FOOTER ───────────────────────────────────────────────────────────
class HeaderFooter:
    def __init__(self, data, tpr):
        self.data = data
        self.tpr  = tpr

    def __call__(self, canvas, doc):
        canvas.saveState()
        w, h = A4
        y = h - 12 * mm
        canvas.setFont("DJB", 13)
        canvas.setFillColor(C_BLACK)
        canvas.drawString(MARGIN, y, self.data["local"])

        # Calcular nombre del día en español a partir de la fecha
        from datetime import datetime
        DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves",
                   "Viernes", "Sábado", "Domingo"]
        try:
            fecha_str = self.data["fecha"]
            # Soporta formatos d/m/yyyy o dd/mm/yyyy
            partes = fecha_str.split("/")
            d, m, anio = int(partes[0]), int(partes[1]), int(partes[2])
            dia_semana = DIAS_ES[datetime(anio, m, d).weekday()]
            fecha_display = f"{dia_semana} {fecha_str}"
        except Exception:
            fecha_display = self.data["fecha"]

        canvas.setFont("DJ", 10)
        canvas.setFillColor(C_GRAY)
        canvas.drawString(MARGIN + 72 * mm, y, fecha_display)
        canvas.setFont("DJ", 9)
        canvas.drawRightString(w - MARGIN, y, f'{doc.page} de {self.tpr[0]}')
        canvas.setStrokeColor(C_LGRAY)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, h - 14.5 * mm, w - MARGIN, h - 14.5 * mm)
        canvas.restoreState()


# ── DATOS ─────────────────────────────────────────────────────────────────────
SAMPLE_DATA = {
    "local": "BILLINGHURST",
    "fecha": "9/4/2026",
    "total_ordenes": 493,
    "resenas_negativas": 9,
    "errores_graves": 2,
    "reclamos": [
        {"fecha": "30/03/2026 14:13", "orden": "460016913", "marca": "Green Eat",
         "platos_pedidos": "Wrap de Pollo / Pan de Queso",
         "platos_reclamados": "servilletas/cubiertos/salsas / Pan de Queso",
         "razon": "INCOMPLETO",
         "comentario": "No llegó mi producto, me llegó un producto de otro restaurante"},
        {"fecha": "30/03/2026 14:26", "orden": "460018159", "marca": "Las Gracias",
         "platos_pedidos": "Milanesa de Pollo Napolitana y Acomp",
         "platos_reclamados": "Elegí Ensalada de Rúcula y Parmesano",
         "razon": "INCOMPLETO",
         "comentario": "La ensalada rúcula parmesano vino sin parmesano"},
        {"fecha": "30/03/2026 20:05", "orden": "460045241", "marca": "Las Gracias",
         "platos_pedidos": "Milanesa de Pollo y Acompañamiento / Espinacas Gratinadas / Tarta de Verdura Individual",
         "platos_reclamados": "Elegí Papas Rústicas",
         "razon": "INCOMPLETO",
         "comentario": "No llegaron las papas"},
        {"fecha": "30/03/2026 20:21", "orden": "460047904", "marca": "Las Gracias",
         "platos_pedidos": "Milanesa de Pollo y Acompañamiento / Milanesa de Pollo Napolitana y Acomp",
         "platos_reclamados": "Milanesa de Pollo y Acompañamiento / Milanesa de Pollo Napolitana y Acomp",
         "razon": "INCORRECTO O DIFERENTE A LO ESPERADO",
         "comentario": "Pedí napolitana"},
        {"fecha": "30/03/2026 22:25", "orden": "460070221", "marca": "Las Gracias",
         "platos_pedidos": "Milanesa de Pollo Napolitana y Acomp",
         "platos_reclamados": "Milanesa de Pollo Napolitana y Acomp",
         "razon": "INCORRECTO O DIFERENTE A LO ESPERADO",
         "comentario": "pedí napolitana y está no tiene nada"},
        {"fecha": "31/03/2026 11:22", "orden": "460092613", "marca": "Green Eat",
         "platos_pedidos": "Summer Salad",
         "platos_reclamados": "Summer Salad",
         "razon": "INCOMPLETO",
         "comentario": "Tenían que llegar 2 ensaladas y sólo vino 1"},
        {"fecha": "31/03/2026 11:38", "orden": "460093764", "marca": "Las Gracias",
         "platos_pedidos": "Milanesa de Pollo Suiza y Acompañamiento / Pepsi Black",
         "platos_reclamados": "",
         "razon": "INCORRECTO O DIFERENTE A LO ESPERADO",
         "comentario": ""},
        {"fecha": "31/03/2026 12:31", "orden": "460099253", "marca": "Green Eat",
         "platos_pedidos": "Poke de Salmón Ahumado / Licuado Detox Green",
         "platos_reclamados": "Poke de Salmón Ahumado",
         "razon": "INCOMPLETO",
         "comentario": "No llegó el salmón, que es el ingrediente principal"},
        {"fecha": "31/03/2026 12:41", "orden": "460100651", "marca": "Green Eat",
         "platos_pedidos": "Pollo Keto",
         "platos_reclamados": "",
         "razon": "INCORRECTO O DIFERENTE A LO ESPERADO",
         "comentario": ""},
        {"fecha": "31/03/2026 13:01", "orden": "460103384", "marca": "Las Gracias",
         "platos_pedidos": "Pastel de Papas Para Compartir",
         "platos_reclamados": "Pastel de Papas Para Compartir",
         "razon": "INCORRECTO O DIFERENTE A LO ESPERADO",
         "comentario": "Pedí pastel de papa para compartir y la porción era para 1 persona"},
        {"fecha": "31/03/2026 13:10", "orden": "460104745", "marca": "Las Gracias",
         "platos_pedidos": "Milanesa de Pollo Suiza y Acompañamiento / Lasagna Mediana",
         "platos_reclamados": "Milanesa de Pollo Suiza y Acompañamiento",
         "razon": "INCOMPLETO",
         "comentario": "Vino una milanesa normal, no suiza (sin queso, sin salsa blanca)"},
        {"fecha": "31/03/2026 22:03", "orden": "460178276", "marca": "Green Eat",
         "platos_pedidos": "Franui Leche / Tiramisú",
         "platos_reclamados": "Tiramisú",
         "razon": "INCOMPLETO",
         "comentario": "Pedí un tiramisú y me trajeron un brownie"},
    ],
    "resenas": [
        {
            "fecha": "30/03/2026 20:47", "orden": "460045241",
            "marca": "Sushi Martina", "app": "Rappi", "estrellas": 1,
            "platos": [
                {"nombre": "Milanesa de Pollo y Acompañamiento",
                 "tags": ["Faltaron algunos items"], "comentario": "", "grave": False},
                {"nombre": "Tarta de Verdura Individual",
                 "tags": ["Faltaron algunos items"], "comentario": "", "grave": False},
                {"nombre": "Espinacas Gratinadas",
                 "tags": ["Faltaron algunos items"], "comentario": "", "grave": False},
            ],
        },
        {
            "fecha": "30/03/2026 21:03", "orden": "460047904",
            "marca": "Sushi Martina", "app": "Rappi", "estrellas": 2,
            "platos": [
                {"nombre": "Milanesa de Pollo y Acompañamiento",
                 "tags": [], "comentario": "Comentario del cliente", "grave": False},
                {"nombre": "Milanesa de Pollo Napolitana y Acomp",
                 "tags": [], "comentario": "Comentario del cliente", "grave": False},
            ],
        },
        {
            "fecha": "30/03/2026 22:48", "orden": "460062713",
            "marca": "Sushi Martina", "app": "Rappi", "estrellas": 1,
            "platos": [
                {"nombre": "Milanesa de Pollo Napolitana y Acomp",
                 "tags": ["Pesima calidad"], "comentario": "", "grave": False},
            ],
        },
        {
            "fecha": "31/03/2026 14:20", "orden": "1952174318",
            "marca": "Ensaladas Sole", "app": "PedidosYa", "estrellas": 1,
            "platos": [
                {"nombre": "Promo Wrap Caesar",
                 "tags": [], "comentario": "", "grave": False},
            ],
        },
        {
            "fecha": "31/03/2026 15:24", "orden": "1952271937",
            "marca": "Ensaladas Sole", "app": "PedidosYa", "estrellas": 1,
            "platos": [
                {"nombre": "Promo Poke Pollo Teriyaki",
                 "tags": ["PROBLEMAS DE CALIDAD"],
                 "comentario": "Plastico adentro de mi comida", "grave": True},
            ],
        },
        {
            "fecha": "31/03/2026 17:00", "orden": "1952426872",
            "marca": "Ensaladas Sole", "app": "PedidosYa", "estrellas": 2,
            "platos": [
                {"nombre": "Promo Tostado Cuatro Quesos y Tomate",
                 "tags": ["PROBLEMAS DE CALIDAD"],
                 "comentario": "No tenia nada de relleno", "grave": False},
            ],
        },
        {
            "fecha": "01/04/2026 12:10", "orden": "1953001122",
            "marca": "Rotiseria Nico", "app": "Mercado Libre", "estrellas": 1,
            "platos": [
                {"nombre": "Pollo al Horno con Papas",
                 "tags": ["Llego frio"],
                 "comentario": "El pollo llego completamente crudo por adentro",
                 "grave": True},
            ],
        },
        {
            "fecha": "01/04/2026 19:35", "orden": "1953045678",
            "marca": "Saludable Isi", "app": "Rappi", "estrellas": 2,
            "platos": [
                {"nombre": "Bowl Proteico Especial",
                 "tags": ["Tardo mucho"],
                 "comentario": "Tardo mas de una hora y llego frio", "grave": False},
            ],
        },
        {
            "fecha": "02/04/2026 20:02", "orden": "1953112233",
            "marca": "Sushi Martina", "app": "PedidosYa", "estrellas": 1,
            "platos": [
                {"nombre": "Combo Sushi 24 piezas",
                 "tags": ["Faltaron algunos items", "Presentacion incorrecta"],
                 "comentario": "Faltaban 8 piezas y venian aplastadas", "grave": False},
            ],
        },
    ],
}


# ── BUILD ─────────────────────────────────────────────────────────────────────
def build_report(data, out_path):
    from pypdf import PdfReader
    styles = make_styles()
    tpr = [1]
    cb  = HeaderFooter(data, tpr)

    def make_doc(fp):
        return SimpleDocTemplate(
            fp, pagesize=A4,
            leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=16 * mm, bottomMargin=14 * mm,
        )

    buf = io.BytesIO()
    make_doc(buf).build(build_story(data, styles, tpr),
                        onFirstPage=cb, onLaterPages=cb)
    buf.seek(0)
    tpr[0] = len(PdfReader(buf).pages)

    make_doc(out_path).build(build_story(data, styles, tpr),
                              onFirstPage=cb, onLaterPages=cb)
    print(f"OK — {out_path}  ({tpr[0]} paginas)")


if __name__ == "__main__":
    build_report(SAMPLE_DATA,
                 "/mnt/user-data/outputs/Billinghurst_2026-04-09_demo.pdf")
