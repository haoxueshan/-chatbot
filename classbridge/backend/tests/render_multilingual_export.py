"""Manual visual QA: run from backend; synthetic sample, no API/database access."""
from pathlib import Path
from app.services.exporting import render_pdf

SAMPLE = '''ClassBridge 多语言导出排版检查
静态 QA 样例；不是模型识别或翻译结果。
00:00-00:08 | 来源版本 2 | 韩英原文
오늘은 작업 기억을 공부합니다. Working memory is important.

简体中文：今天学习工作记忆。繁體中文：今天學習工作記憶。
英语：Today we study working memory.
韩语：오늘은 작업 기억을 공부합니다.
日语：今日はワーキングメモリについて学びます。
法语：Nous étudions la mémoire de travail.
德语：Heute untersuchen wir das Arbeitsgedächtnis.
西班牙语：Hoy estudiamos la memoria de trabajo.
俄语：Сегодня мы изучаем рабочую память.
葡萄牙语：Hoje estudamos a memória de trabalho.
意大利语：Oggi studiamo la memoria di lavoro.
泰语：วันนี้เราเรียนเรื่องความจำ
越南语：Hôm nay chúng ta học về trí nhớ làm việc.

阿拉伯语（字形连接、数字、英文与自动换行检查）：
اليوم ندرس الذاكرة العاملة. Working memory 2026.
مرحبا بالعالم. هذه ترجمة للمحاضرة. ''' + 'نحافظ على النص الأصلي ونراجع الأدلة قبل الوصول إلى الاستنتاجات. ' * 8

if __name__ == '__main__':
    destination=Path(__file__).resolve().parents[2]/'.local/output/pdf/multilingual-subtitles.pdf'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_bytes(render_pdf(SAMPLE))
    print(destination)
