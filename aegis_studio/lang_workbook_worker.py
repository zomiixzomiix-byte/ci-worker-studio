"""Illustrated A4 Arabic-German Workbook PDF Generator for Language Studio Academy.

Builds a crisp, print-ready A4 PDF workbook per lesson using Playwright Chromium:
  - Color-coded Vocabulary Tables (der=#3B82F6, die=#F43F5E, das=#10B981, Pl=#F59E0B)
  - Structured Grammar Reference Sheets & Phonetics Clinic
  - 45 Brand-New Progressive Exercises (Parts A-E)
  - Full Answer Key (Lösungsschlüssel) on dedicated concluding pages.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

ART_COLORS = {
    "der": ("#1D4ED8", "#DBEAFE", "مذكر"),
    "die": ("#BE123C", "#FFE4E6", "مؤنث"),
    "das": ("#047857", "#D1FAE5", "محايد"),
    "expr": ("#B45309", "#FEF3C7", "تعبير"),
    "verb": ("#6D28D9", "#EDE9FE", "فعل"),
}


def render_workbook_html(curriculum: dict[str, Any]) -> str:
    """Render styled RTL/LTR A4 HTML document from curriculum['workbook']."""
    wb = curriculum["workbook"]
    vocab = wb.get("vocab", [])
    grams = wb.get("grammar_tables", [])
    phons = wb.get("phonetics", [])
    sections = wb.get("sections", [])
    ab_sols = wb.get("ab_solutions", [])

    vocab_rows = ""
    for v in vocab:
        art = str(v.get("art") or "expr")
        fg, bg, ar_t = ART_COLORS.get(art, ART_COLORS["expr"])
        vocab_rows += f"""
        <tr>
          <td><span class="tag" style="color:{fg};background:{bg};border-color:{fg}44">{html.escape(ar_t)}</span></td>
          <td dir="ltr" class="de-cell"><strong>{html.escape(str(v['de']))}</strong><br><span class="pl">Pl.: {html.escape(str(v.get('pl','—')))}</span></td>
          <td dir="ltr" class="ipa-cell">{html.escape(str(v.get('ipa','')))}</td>
          <td class="pron-cell">{html.escape(str(v.get('ar_pron','')))}</td>
          <td><strong>{html.escape(str(v.get('ar','')))}</strong><br><span class="ex" dir="ltr">{html.escape(str(v.get('ex_de','')))}</span></td>
        </tr>"""

    gram_blocks = ""
    for g in grams:
        hdrs = "".join(f"<th>{html.escape(str(h))}</th>" for h in g["headers"])
        rows_html = ""
        for r in g["rows"]:
            tds = "".join(f"<td>{html.escape(str(c))}</td>" for c in r)
            rows_html += f"<tr>{tds}</tr>"
        gram_blocks += f"""
        <div class="card">
          <h3>{html.escape(str(g['title']))}</h3>
          <table class="gram-tbl"><thead><tr>{hdrs}</tr></thead><tbody>{rows_html}</tbody></table>
          <div class="rule-note">💡 <strong>القاعدة الذهبية:</strong> {html.escape(str(g.get('rule_ar','')))}</div>
        </div>"""

    phon_cards = ""
    for p in phons:
        exs = " &nbsp;•&nbsp; ".join(html.escape(e) for e in p.get("examples", []))
        phon_cards += f"""
        <div class="phon-item">
          <div class="phon-top"><span class="de-badge" dir="ltr">{html.escape(str(p['symbol']))}</span> <span class="ipa-mini" dir="ltr">{html.escape(str(p['ipa']))}</span></div>
          <p>{html.escape(str(p['ar_guide']))}</p>
          <div class="phon-ex" dir="ltr">{exs}</div>
          <div class="phon-tip">✓ {html.escape(str(p['tip']))}</div>
        </div>"""

    ex_sections_html = ""
    ans_sections_html = ""
    for sec in sections:
        ex_items = ""
        ans_items = ""
        for it in sec["items"]:
            ex_items += f"""
            <div class="q-item">
              <span class="q-num">{html.escape(it['num'])}</span>
              <div class="q-body">
                <div class="q-txt">{html.escape(it['prompt'])}</div>
                <div class="write-line"></div>
              </div>
            </div>"""
            ans_items += f"""
            <div class="ans-item"><strong>{html.escape(it['num'])}:</strong> {html.escape(it['answer'])}</div>"""
        ex_sections_html += f"""
        <div class="sec-box">
          <h3>{html.escape(sec['title'])}</h3>
          {ex_items}
        </div>"""
        ans_sections_html += f"""
        <div class="ans-box">
          <h4>{html.escape(sec['title'])}</h4>
          {ans_items}
        </div>"""

    ab_html = "".join(
        f'<div class="ab-row"><strong>{html.escape(a["ex"])}:</strong> {html.escape(a["solution"])}</div>'
        for a in ab_sols
    )

    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8" />
<style>
  @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@500;700;800&family=Noto+Sans:wght@500;700;800&display=swap');
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Cairo', 'Noto Sans Arabic', 'DejaVu Sans', sans-serif;
    color: #0F172A; font-size: 11pt; line-height: 1.5; background: #FFFFFF;
  }}
  .hero {{
    background: linear-gradient(135deg, #0B132B, #1E293B);
    color: #F8FAFC; border-radius: 14px; padding: 22px 24px; margin-bottom: 16px;
    border-bottom: 5px solid #F59E0B;
  }}
  .hero-top {{ display: flex; justify-content: space-between; align-items: center; font-size: 9.5pt; color: #FCD34D; font-weight: 700; margin-bottom: 6px; }}
  .hero h1 {{ font-size: 19pt; font-weight: 800; margin-bottom: 4px; }}
  .hero p {{ font-size: 11pt; color: #CBD5E1; }}
  .legend {{
    display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px;
    padding: 8px 12px; border: 1px solid #E2E8F0; border-radius: 10px; background: #F8FAFC; font-size: 9.5pt;
  }}
  .tag {{ display: inline-block; padding: 2px 8px; border-radius: 6px; border: 1px solid; font-weight: 700; font-size: 8.5pt; }}
  h2 {{ font-size: 13.5pt; color: #0F172A; border-right: 5px solid #2563EB; padding-right: 10px; margin: 18px 0 10px; }}
  h3 {{ font-size: 11.5pt; color: #1E293B; margin-bottom: 8px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; font-size: 9.5pt; }}
  th {{ background: #1E293B; color: #FFF; padding: 7px 8px; text-align: right; font-weight: 700; }}
  td {{ border-bottom: 1px solid #E2E8F0; padding: 7px 8px; vertical-align: top; }}
  tr:nth-child(even) td {{ background: #F8FAFC; }}
  .de-cell {{ font-family: 'Noto Sans', sans-serif; text-align: left; font-size: 10pt; }}
  .pl {{ color: #B45309; font-size: 8.5pt; }}
  .ipa-cell {{ font-family: monospace; text-align: left; color: #475569; font-size: 8.8pt; }}
  .pron-cell {{ color: #6D28D9; font-weight: 700; font-size: 10pt; }}
  .ex {{ color: #334155; font-size: 8.8pt; display: inline-block; margin-top: 2px; }}
  .card {{ border: 1px solid #CBD5E1; border-radius: 10px; padding: 12px 14px; margin-bottom: 12px; page-break-inside: avoid; }}
  .rule-note {{ background: #FEF3C7; color: #92400E; border-right: 4px solid #F59E0B; padding: 7px 10px; border-radius: 6px; font-size: 9.5pt; margin-top: 6px; }}
  .phon-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px; }}
  .phon-item {{ border: 1px solid #CBD5E1; border-radius: 10px; padding: 10px 12px; background: #F8FAFC; page-break-inside: avoid; }}
  .phon-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }}
  .de-badge {{ background: #0F172A; color: #FCD34D; padding: 2px 8px; border-radius: 6px; font-weight: 800; font-size: 9.5pt; }}
  .ipa-mini {{ font-family: monospace; color: #475569; font-size: 9pt; }}
  .phon-ex {{ font-family: 'Noto Sans', sans-serif; color: #1D4ED8; font-weight: 700; margin: 4px 0; font-size: 9.5pt; }}
  .phon-tip {{ color: #047857; font-size: 9pt; font-weight: 700; }}
  .sec-box {{ margin-bottom: 14px; page-break-inside: avoid; }}
  .q-item {{ display: flex; gap: 8px; align-items: flex-start; margin-bottom: 8px; padding: 6px 8px; border: 1px solid #E2E8F0; border-radius: 8px; page-break-inside: avoid; }}
  .q-num {{ background: #2563EB; color: #FFF; border-radius: 6px; padding: 2px 7px; font-weight: 800; font-size: 8.5pt; flex-shrink: 0; }}
  .q-body {{ flex: 1; }}
  .q-txt {{ font-size: 9.8pt; font-weight: 600; }}
  .write-line {{ border-bottom: 1.5px dashed #94A3B8; height: 18px; margin-top: 4px; }}
  .page-break {{ page-break-before: always; }}
  .ans-box {{ border: 1px solid #CBD5E1; border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; background: #F0FDF4; page-break-inside: avoid; }}
  .ans-box h4 {{ color: #166534; margin-bottom: 6px; font-size: 10.5pt; }}
  .ans-item {{ font-size: 9pt; margin-bottom: 3px; color: #1E293B; }}
  .ab-row {{ font-size: 9pt; padding: 5px 8px; border-bottom: 1px solid #E2E8F0; }}
</style>
</head>
<body>
  <div class="hero">
    <div class="hero-top">
      <span>MENSCHEN {html.escape(wb['level'])} • LEKTION {wb['lektion']:02d} • ÜBUNGSHEFT (WORKBOOK)</span>
      <span>نسبة الألمانية: {int(round(wb['de_ratio']*100))}%</span>
    </div>
    <h1 dir="ltr" style="text-align:left;">{html.escape(wb['title_de'])}</h1>
    <p>{html.escape(wb['title_ar'])} — كتاب التمارين المخصّص والمرفق بالفيديو (45 تمريناً مع الحلول)</p>
  </div>

  <div class="legend">
    <span><strong>شيفرة الألوان العلمية:</strong></span>
    <span class="tag" style="color:#1D4ED8;background:#DBEAFE;border-color:#1D4ED844">der = مذكر</span>
    <span class="tag" style="color:#BE123C;background:#FFE4E6;border-color:#BE123C44">die = مؤنث</span>
    <span class="tag" style="color:#047857;background:#D1FAE5;border-color:#04785744">das = محايد</span>
    <span class="tag" style="color:#B45309;background:#FEF3C7;border-color:#B4530944">die (Pl.) / تعابير</span>
    <span class="tag" style="color:#6D28D9;background:#EDE9FE;border-color:#6D28D944">Verb = فعل</span>
  </div>

  <h2>1. خزينة المفردات الملوّنة والنطق الصوتي (Wortschatz-Matrix)</h2>
  <table>
    <thead><tr><th>النوع</th><th>الألمانية + الجمع</th><th>IPA</th><th>النطق العربي</th><th>المعنى والمثال</th></tr></thead>
    <tbody>{vocab_rows}</tbody>
  </table>

  <h2>2. ملخص القواعد الهندسية (Grammatik-Übersicht)</h2>
  {gram_blocks}

  <h2>3. مختبر الصوتيات والنطق السليم (Phonetik-Leitfaden)</h2>
  <div class="phon-grid">{phon_cards}</div>

  <div class="page-break"></div>
  <h2>4. كتاب التمارين التطبيقي المتدرّج (45 تمريناً جديداً)</h2>
  {ex_sections_html}

  <div class="page-break"></div>
  <h2>5. دليل الحلول النموذجية الكاملة (Lösungsschlüssel)</h2>
  {ans_sections_html}

  <h2>6. ملخص حلول كتاب النشاط الرسمي (Arbeitsbuch Lösungen)</h2>
  <div class="card">{ab_html}</div>
</body>
</html>
"""


def build_workbook_pdf(curriculum_path: Path, out_pdf: Path) -> Path:
    """Render printable A4 PDF workbook cleanly via Playwright Chromium."""
    from playwright.sync_api import sync_playwright

    curriculum = json.loads(curriculum_path.read_text(encoding="utf-8"))
    html_str = render_workbook_html(curriculum)
    html_tmp = out_pdf.with_suffix(".html")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    html_tmp.write_text(html_str, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page()
        page.goto(html_tmp.resolve().as_uri(), wait_until="networkidle")
        page.evaluate("() => document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()")
        page.pdf(
            path=str(out_pdf),
            format="A4",
            print_background=True,
            margin={"top": "12mm", "bottom": "12mm", "left": "11mm", "right": "11mm"},
        )
        browser.close()
    print(f"LANG_WORKBOOK_PDF_OK: {out_pdf} ({out_pdf.stat().st_size // 1024} KB)", flush=True)
    return out_pdf


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate A4 German-Arabic PDF Workbook")
    parser.add_argument("--curriculum", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build_workbook_pdf(args.curriculum, args.out)


if __name__ == "__main__":
    main()
