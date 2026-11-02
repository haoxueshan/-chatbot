"""Readable, embedded-font CJK exports. No browser or model dependency."""
from functools import lru_cache
from html import escape
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


@lru_cache(maxsize=1)
def export_fonts():
    # TrueType fonts are embedded. Noto CJK's CFF collections cannot be embedded
    # by ReportLab TTFont; use packaged Nanum/WenQuanYi in the Linux container.
    candidates = [
        ("CBLatin", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ("CBLatinWin", "C:/Windows/Fonts/arial.ttf"),
        ("CBChinese", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        ("CBChineseWin", "C:/Windows/Fonts/msyh.ttc"),
        ("CBKorean", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
        ("CBKoreanWin", "C:/Windows/Fonts/malgun.ttf"),
    ]
    result = []
    for name, filename in candidates:
        if Path(filename).is_file():
            font = TTFont(name, filename, subfontIndex=0)
            pdfmetrics.registerFont(font)
            result.append((name, font.face.charToGlyph))
    if not result:
        raise RuntimeError("PDF导出缺少中韩文字体，请安装 fonts-wqy-zenhei 和 fonts-nanum。")
    return result


def font_for(character: str):
    for name, glyphs in export_fonts():
        if ord(character) in glyphs:
            return name
    # Explicit replacement for unsupported symbols, never a missing CJK glyph.
    return export_fonts()[0][0]


def rich_text(text: str):
    groups = []
    active, run = None, ""
    for char in text:
        if ord(char) < 32:
            char = " "
        selected = font_for(char)
        if active is not None and selected != active:
            groups.append(f'<font name="{active}">{escape(run)}</font>')
            run = ""
        active = selected
        run += char
    if run:
        groups.append(f'<font name="{active}">{escape(run)}</font>')
    return "".join(groups)


def render_pdf(content: str, title: str = "ClassBridge 会话记录") -> bytes:
    output = BytesIO()
    font = export_fonts()[0][0]
    body = ParagraphStyle("body", fontName=font, fontSize=10.5, leading=17,
                          wordWrap="CJK", textColor=colors.HexColor("#253047"),
                          spaceAfter=5, alignment=TA_LEFT)
    heading = ParagraphStyle("heading", parent=body, fontSize=18, leading=26,
                             textColor=colors.HexColor("#3730a3"), spaceAfter=14)
    document = SimpleDocTemplate(output, pagesize=A4, title=title, author="ClassBridge",
                                 topMargin=54, bottomMargin=52, leftMargin=45, rightMargin=45)
    flow = []
    for index, line in enumerate(content.splitlines()):
        if not line.strip():
            flow.append(Spacer(1, 6))
            continue
        flow.append(Paragraph(rich_text(line.lstrip("# ") if index == 0 else line), heading if index == 0 else body))

    def page(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#e4e7ef"))
        canvas.line(45, 36, A4[0] - 45, 36)
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(45, 23, "ClassBridge | Private session export")
        canvas.drawRightString(A4[0] - 45, 23, str(doc.page))
        canvas.restoreState()

    document.build(flow, onFirstPage=page, onLaterPages=page)
    return output.getvalue()
