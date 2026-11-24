# -*- coding: utf-8 -*-
"""Genera docs/Manual_Bomba_de_Jeringa.pdf (requiere: pip install reportlab)."""
import os
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether,
                                PageTemplate, Paragraph, Spacer, Table,
                                TableStyle, PageBreak)

HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.path.join(HERE, "img")
OUT = os.path.join(HERE, "Manual_Bomba_de_Jeringa.pdf")

# ---------- Fuentes ----------
FONT, BOLD = "Helvetica", "Helvetica-Bold"
win = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
try:
    pdfmetrics.registerFont(TTFont("Segoe", os.path.join(win, "segoeui.ttf")))
    pdfmetrics.registerFont(TTFont("SegoeB", os.path.join(win, "segoeuib.ttf")))
    FONT, BOLD = "Segoe", "SegoeB"
except Exception:
    pass

BLUE = colors.HexColor("#2563eb")
DARK = colors.HexColor("#0f172a")
TEXT = colors.HexColor("#374151")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#e5e7eb")
SOFT = colors.HexColor("#eff6ff")
AMBER_BG = colors.HexColor("#fffbeb")
AMBER = colors.HexColor("#92400e")

W, H = A4
M = 18 * mm
CW = W - 2 * M

s_body = ParagraphStyle("body", fontName=FONT, fontSize=10.5, leading=15.5,
                        textColor=TEXT, alignment=TA_LEFT)
s_h1 = ParagraphStyle("h1", fontName=BOLD, fontSize=19, leading=24,
                      textColor=DARK, spaceBefore=4, spaceAfter=8)
s_num = ParagraphStyle("num", fontName=BOLD, fontSize=10, leading=12,
                       textColor=BLUE)
s_cap = ParagraphStyle("cap", parent=s_body, fontSize=9, leading=12,
                       textColor=MUTED, alignment=1)
s_step = ParagraphStyle("step", parent=s_body, leftIndent=0)
s_tip = ParagraphStyle("tip", parent=s_body, fontSize=10, leading=14.5)
s_cell = ParagraphStyle("cell", parent=s_body, fontSize=9.5, leading=13.5)
s_cellb = ParagraphStyle("cellb", parent=s_cell, fontName=BOLD,
                         textColor=DARK)


def P(text, style=s_body):
    return Paragraph(text, style)


def b(text):
    return "<font name='%s' color='#0f172a'>%s</font>" % (BOLD, text)


def section(num, title):
    return KeepTogether([Spacer(1, 6), P("%02d" % num, s_num), P(title, s_h1)])


def shot(name, width=CW, caption=None, flat=False):
    path = os.path.join(IMG, name + ".png")
    iw, ih = ImageReader(path).getSize()
    img = Image(path, width=width, height=width * ih / iw)
    t = Table([[img]], colWidths=[width + 2])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    items = [t]
    if caption:
        items += [Spacer(1, 4), P(caption, s_cap)]
    return items if flat else KeepTogether(items)


def steps(items):
    """Lista numerada con circulos azules."""
    rows = []
    for i, text in enumerate(items, 1):
        badge = Table([[P("<font color='white'>%d</font>" % i,
                          ParagraphStyle("bd", fontName=BOLD, fontSize=9.5,
                                         leading=11, alignment=1))]],
                      colWidths=[6.5 * mm], rowHeights=[6.5 * mm])
        badge.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BLUE),
            ("ROUNDEDCORNERS", [3.25 * mm] * 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        rows.append([badge, P(text, s_step)])
    t = Table(rows, colWidths=[10 * mm, CW - 10 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (1, 0), (1, -1), 0),
    ]))
    return t


def box(text, warn=False):
    t = Table([[P(text, s_tip)]], colWidths=[CW])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), AMBER_BG if warn else SOFT),
        ("ROUNDEDCORNERS", [8, 8, 8, 8]),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def table(rows, widths):
    data = [[P(c, s_cellb if r == 0 or i == 0 else s_cell)
             for i, c in enumerate(row)] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f5f9")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def grid2(a, b_, ca, cb):
    w = (CW - 6 * mm) / 2
    t = Table([[shot(a, w, ca, True), shot(b_, w, cb, True)]], colWidths=[w + 3 * mm] * 2)
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return t


# ---------- Paginas ----------
def first_page(c, doc):
    c.saveState()
    c.setFillColor(BLUE)
    c.rect(0, H - 62 * mm, W, 62 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(BOLD, 30)
    c.drawString(M, H - 32 * mm, "Bomba de Jeringa")
    c.setFont(FONT, 13)
    c.drawString(M, H - 42 * mm, "Manual de usuario  ·  software v2.1")
    c.restoreState()
    footer(c, doc)


def footer(c, doc):
    c.saveState()
    c.setFont(FONT, 8.5)
    c.setFillColor(MUTED)
    c.drawString(M, 10 * mm, "Bomba de Jeringa — Manual de usuario")
    c.drawRightString(W - M, 10 * mm, str(doc.page))
    c.restoreState()


doc = BaseDocTemplate(OUT, pagesize=A4, leftMargin=M, rightMargin=M,
                      topMargin=M, bottomMargin=18 * mm,
                      title="Bomba de Jeringa — Manual de usuario",
                      author="Bomba de Jeringa")
frame_first = Frame(M, 18 * mm, CW, H - 62 * mm - 18 * mm - 8 * mm, id="f1")
frame = Frame(M, 18 * mm, CW, H - M - 18 * mm, id="f")
doc.addPageTemplates([PageTemplate("first", [frame_first], onPage=first_page),
                      PageTemplate("rest", [frame], onPage=footer)])

story = []
from reportlab.platypus import NextPageTemplate
story.append(NextPageTemplate("rest"))

# 1. Que necesitas
story.append(section(1, "Qué necesitas"))
story.append(table([
    ["Elemento", "Detalle"],
    ["Bomba de jeringa", "Con su fuente de alimentación de 12 V."],
    ["Cable USB", "Conecta la bomba al computador."],
    ["Computador", "Windows 10 u 11, con el archivo <b>BombaJeringa.exe</b>."],
], [45 * mm, CW - 45 * mm]))
story.append(Spacer(1, 8))
story.append(box(b("Importante: ") + "la bomba se controla desde el "
                 "computador. El cable USB debe quedar conectado mientras "
                 "la bomba trabaja; si se desconecta, el movimiento se "
                 "detiene."))

# 2. Primer uso
story.append(section(2, "Conectar y abrir el programa"))
story.append(steps([
    "Conecta la fuente de 12 V a la bomba y enchúfala.",
    "Conecta el cable USB entre la bomba y el computador.",
    "Abre " + b("BombaJeringa.exe") + ". No requiere instalación.",
    "Pulsa " + b("Conectar") + " arriba a la derecha. El indicador se pone "
    "verde: " + b("Conectado") + ".",
]))
story.append(box("La primera vez, Windows puede mostrar «Windows protegió "
                 "su PC». Pulsa " + b("Más información") + " y luego " +
                 b("Ejecutar de todas formas") + ".", warn=True))

# 3. Dosificar
story.append(PageBreak())
story.append(section(3, "Dosificar"))
story.append(shot("16_cranberry"))
story.append(Spacer(1, 10))
story.append(steps([
    b("Jeringa") + ": elige el modelo que montaste en la bomba.",
    b("Infundir") + " empuja el émbolo (sale líquido). " + b("Retirar") +
    " lo tira hacia atrás (entra líquido).",
    b("Volumen") + " y " + b("Caudal") + ": escribe los valores y elige "
    "las unidades. Debajo aparece la duración.",
    "Pulsa " + b("Iniciar") + ". El botón amarillo pausa y el rojo detiene.",
]))
story.append(Spacer(1, 4))
story.append(shot("03_dosificando", CW * 0.78,
                  "Durante la dosificación, el anillo muestra el volumen "
                  "entregado y el tiempo restante."))

# 4. Mover embolo
story.append(section(4, "Mover el émbolo a mano"))
story.append(P("En la parte inferior de " + b("Dosificar") + " están los "
               "botones Avanzar y Retroceder para acercar el carro al émbolo, cargar la jeringa "
               "o sacar burbujas."))
story.append(Spacer(1, 6))
story.append(table([
    ["Opción", "Qué hace"],
    ["0,01 · 0,1 · 1,0 mL", "Cada clic mueve ese volumen."],
    ["Mantener", "Mantén presionado el botón: se mueve mientras lo "
                 "sostienes y se detiene al soltar."],
    ["Avanzar", "Empuja el émbolo."],
    ["Retroceder", "Tira el émbolo hacia atrás (aspira)."],
    ["Retroceder todo", "Lleva el carro hacia atrás, rápido, para cargar o cambiar la jeringa. Púlsalo otra vez para detenerlo. La distancia se ajusta en Ajustes (60 mm de fábrica)."],
], [45 * mm, CW - 45 * mm]))

# 5. Jeringa nueva
story.append(PageBreak())
story.append(section(5, "Registrar una jeringa nueva"))
story.append(P("Cada marca tiene un diámetro interior distinto, aunque diga "
               "la misma capacidad. Para que el volumen sea exacto, registra "
               "cada modelo " + b("una sola vez") + ": pestaña " +
               b("Jeringas") + " → " + b("Nueva jeringa") + "."))
story.append(Spacer(1, 10))
story.append(grid2("07_wiz_info", "08_wiz_metodo",
                   "1 · Nombre y capacidad", "2 · Elige «Con la bomba»"))
story.append(Spacer(1, 8))
story.append(grid2("09_wiz_alinear", "10_wiz_mover",
                   "3 · Alinea el émbolo con una marca",
                   "4 · La bomba avanza una distancia"))
story.append(Spacer(1, 8))
story.append(steps([
    "Llena la jeringa con agua, sin burbujas, y móntala.",
    "Con los botones −1 mm … +1 mm, deja el borde del émbolo justo sobre una marca. "
    "Anota esa lectura (o tara la balanza con un vaso bajo la punta).",
    "Pulsa " + b("Mover ahora") + ".",
    "Escribe la nueva lectura de la escala (o los gramos de agua: "
    "1 g ≈ 1 mL) y pulsa " + b("Guardar") + ".",
]))
story.append(box(b("Ojo: ") + "la bomba no detecta el fondo de la jeringa. "
                 "Usa una distancia que deje al menos 1 mL dentro; el "
                 "programa avisa si la distancia la vaciaría.", warn=True))
story.append(Spacer(1, 6))
story.append(box("Con balanza el resultado es más preciso. Si conoces el "
                 "diámetro interior exacto (calibre o ficha del fabricante), "
                 "puedes elegir " + b("Por diámetro") + " en el paso 2."))

# 6. Ajustes
story.append(PageBreak())
story.append(section(6, "Ajustes (servicio técnico)"))
story.append(P("Normalmente no hay que tocar esta pestaña."))
story.append(Spacer(1, 6))
story.append(shot("15_ajustes", CW * 0.85))
story.append(Spacer(1, 8))
story.append(table([
    ["Ajuste", "Para qué sirve"],
    ["Invertir sentido", "Si al avanzar el carro se aleja de la jeringa."],
    ["Calibrar tornillo", "Pulsa Mover, mide con un calibre cuánto avanzó "
                          "el carro, escríbelo y pulsa Aplicar. Empieza con 5 mm."],
    ["Tornillo", "Debe coincidir con el del equipo: T8 de 1 entrada = 2 mm por vuelta. Si está mal, la bomba mueve varias veces más o menos de lo pedido."],
    ["Valores de fábrica", "Tornillo T8 (2 mm/vuelta) · microstepping 16 · 200 pasos."],
], [45 * mm, CW - 45 * mm]))
story.append(Spacer(1, 6))
story.append(P("Las jeringas y la configuración se guardan solas en "
               "<font name='%s'>%%APPDATA%%\\BombaJeringa</font>. Para "
               "pasarlas a otro computador, copia esa carpeta." % FONT))

# 7. Problemas
story.append(section(7, "Problemas frecuentes"))
story.append(table([
    ["Problema", "Solución"],
    ["No aparece la bomba", "Revisa el cable USB. Si sigue sin aparecer, "
                            "instala el driver CH340 (placas genéricas)."],
    ["«No se pudo conectar»", "Cierra otros programas que usen el puerto, "
                              "como el Monitor Serie de Arduino."],
    ["El carro va al revés", "Ajustes → Invertir sentido del motor."],
    ["El volumen no coincide", "Calibra esa jeringa con la bomba (sección 5)."],
    ["El motor vibra y no avanza", "Revisa la fuente de 12 V. Baja el caudal "
                                   "o la aceleración."],
], [50 * mm, CW - 50 * mm]))

# 8. Especificaciones
story.append(section(8, "Especificaciones"))
story.append(table([
    ["Dato", "Valor"],
    ["Alimentación", "12 V CC, 2 A mínimo (conector según el equipo)."],
    ["Conexión", "USB (el Arduino se alimenta por el mismo cable)."],
    ["Caudal máximo", "Depende de la jeringa; se muestra en Ajustes."],
    ["Resolución", "1.600 pasos por mm (≈ 0,1 µL por paso con 10 mL)."],
], [45 * mm, CW - 45 * mm]))

doc.build(story)
print("PDF generado:", OUT)
