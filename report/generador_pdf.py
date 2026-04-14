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

GAUGE_COLORS = [
    "#2a9d2a", "#78c142", "#f0e020",
    "#f0a020", "#e05818", "#cc1111",
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

    def draw(self):
        c  = self.canv
        cx = self.width / 2
        cy = 4

        for i, color in enumerate(GAUGE_COLORS):
            a_start = 180 - i * 30
            a_end   = 180 - (i + 1) * 30
            self._segment(c, cx, cy, self.R_OUT, self.R_IN, a_start, a_end, color)

        # Semicírculo gris — solo la mitad superior (0° a 180°)
        r = self.R_IN - 1
        c.setFillColor(C_BGRAY)
        c.setStrokeColor(C_BGRAY)
        c.setLineWidth(0)
        path = c.beginPath()
        path.moveTo(cx - r, cy)                          # extremo izquierdo
        path.arcTo(cx - r, cy - r, cx + r, cy + r, 180, -180)  # arco superior
        path.lineTo(cx - r, cy)                          # cerrar
        path.close()
        c.drawPath(path, fill=1, stroke=0)

        needle_angle = radians(180 - self.pct * 180 / 100)
        nx = cx + self.NEEDLE * cos(needle_angle)
        ny = cy + self.NEEDLE * sin(needle_angle)
        c.setStrokeColor(black)
        c.setLineWidth(2.2)
        c.line(cx, cy, nx, ny)

        c.setFillColor(black)
        c.setStrokeColor(white)
        c.setLineWidth(0.8)
        c.circle(cx, cy, self.R_HUB, fill=1, stroke=1)

        lh = 17
        lw = self.width           # ancho completo sin margen
        ly = -(lh + 4)
        c.setFillColor(C_LABEL_BG)
        c.setStrokeColor(C_LGRAY)
        c.setLineWidth(0.6)
        c.roundRect(0, ly, lw, lh, 3, fill=1, stroke=1)
        c.setFillColor(C_BLACK)
        c.setFont("DJB", 8)
        c.drawCentredString(cx, ly + 5,
                            f"{self.label}: %{self.pct}  |  {self.num} de {self.den}")


class GaugePair(Flowable):
    def __init__(self, neg, tot, grav):
        super().__init__()
        self.neg   = neg
        self.tot   = tot
        self.grav  = grav
        self.gw    = 175
        self.width  = CONTENT_W
        self.height = 62 + 14

    def draw(self):
        c   = self.canv
        gw  = self.gw
        gap = (self.width - 2 * gw) / 2
        x1  = gap / 2
        x2  = x1 + gw + gap

        for x, label, num, den in [
            (x1, "ORDENES CON ERROR", self.neg,  self.tot),
            (x2, "ERRORES GRAVES",    self.grav, self.neg),
        ]:
            g = Gauge(label, num, den, w=gw)
            c.saveState()
            c.translate(x, 22)
            g.canv = c
            g.draw()
            c.restoreState()


# ── FLOWABLE: BADGE ERROR GRAVE ───────────────────────────────────────────────
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


# ── STORY ─────────────────────────────────────────────────────────────────────
def build_story(data, styles, tpr):
    neg      = data["resenas_negativas"]
    tot      = data["total_ordenes"]
    grav     = data["errores_graves"]
    reclamos = data.get("reclamos", [])
    story = []

    # gauges
    story.append(GaugePair(neg, tot, grav))
    story.append(Spacer(1, 4 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LGRAY, spaceAfter=0))
    from reportlab.lib.styles import ParagraphStyle as _PS
    _sec = _PS("sec", fontName="DJB", fontSize=15, textColor=C_BLACK,
               leading=22, spaceBefore=5, spaceAfter=5,
               backColor=HexColor("#EFEFED"), leftIndent=8)
    story.append(Paragraph("RESEÑAS", _sec))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LGRAY, spaceAfter=4 * mm))

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
                    Paragraph(rc["marca"] + "  ·  Rappi", styles["brand_right"]),
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
        canvas.setFont("DJ", 10)
        canvas.setFillColor(C_GRAY)
        canvas.drawString(MARGIN + 72 * mm, y, self.data["fecha"])
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
            topMargin=32 * mm, bottomMargin=14 * mm,
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
