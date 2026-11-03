from io import BytesIO

from pypdf import PdfReader

from app.services.exporting import export_fonts, render_pdf


def test_multilingual_pdf_embeds_fonts_and_preserves_text():
    text = "课堂证据记录\n模式：模拟演示\n00:00–00:12\n오늘은 검색 증강 생성을 배웁니다.\n今天学习检索增强生成。\nHybrid retrieval & evidence <source>"
    fonts = export_fonts()
    for char in "课堂证据记录오늘은검색증강생성을배웁니다":
        assert any(ord(char) in glyphs for _, glyphs in fonts), f"Missing PDF glyph: {char}"
    pdf = render_pdf(text, "ClassBridge 测试")
    reader = PdfReader(BytesIO(pdf))
    extracted = "\n".join(page.extract_text() for page in reader.pages)
    assert "今天学习检索增强生成" in extracted
    assert "오늘은 검색 증강 생성을 배웁니다" in extracted
    assert "Hybrid retrieval & evidence <source>" in extracted
    assert len(reader.pages) == 1


def test_pdf_long_transcript_paginates():
    reader = PdfReader(BytesIO(render_pdf("课堂\n" + "原文 Evidence 증거\n" * 100)))
    assert len(reader.pages) >= 3


def test_japanese_korean_arabic_and_thai_glyphs_and_rtl_line_order():
    from app.services.exporting import visual_rtl, rtl_lines, text_width
    sample='课堂 日本語の翻訳 한국어 번역 ภาษาไทย Tiếng Việt العربية مرحبا بالعالم'
    for char in visual_rtl(sample):
        assert any(ord(char) in glyphs for _,glyphs in export_fonts()),f'Missing export glyph U+{ord(char):04X}'
    logical='مرحبا بالعالم. هذه ترجمة للمحاضرة. ' * 30
    lines=rtl_lines(logical,300,10.5)
    assert len(lines)>2 and all(text_width(line,10.5)<=300 for line in lines)
    assert lines[0].endswith(visual_rtl('مرحبا بالعالم.'))
    pdf=render_pdf('多语言字幕\n日本語の翻訳\n한국어 번역\n'+logical)
    reader=PdfReader(BytesIO(pdf));extracted='\n'.join(p.extract_text() for p in reader.pages)
    assert '日本語の翻訳' in extracted and '한국어 번역' in extracted
