"""Language Master Academy — 1920x1080 Interactive 3D CSS & Ken Burns HTML5 Stage Builder.

Renders 9 specialized interactive German/Arabic instructional boards synced to real-time RMS audio:
  1. BOOK_KEN_BURNS_SPOTLIGHT   - 3D tilted Kursbuch page with progressive pan/zoom & glow spotlight
  2. HUEBER_AUDIO_CINEMA        - Dark cinema studio with 32-bar RMS audio spectrum + transcript
  3. DER_DIE_DAS_COLOR_STAGE    - Scientific color-coded gender matrix (der=blue, die=rose, das=emerald)
  4. GRAMMAR_SYNTAX_ENGINE      - Interactive Satzbau position-II diagram + laser table highlight
  5. PHONETIK_ARTICULATION_LAB  - Speech lab with Arabic articulation guide, IPA & waveform ring
  6. ARBEITSBUCH_LIVE_SOLVER    - Scanned Arbeitsbuch zoom + Hueber official Loesung scanner overlay
  7. DIALOGUE_DUAL_IMMERSION    - Dual-voice German/Arabic roleplay cards (Aoede & Charon)
  8. INTERACTIVE_DRILL_ARENA    - Goethe-Institut timed MCQ arena + verified explanation reveal
  9. FINALE_DIPLOMA_STAGE       - Fullscreen 3D gold-bevelled course certificate & companion links
"""

from __future__ import annotations

import argparse
import base64
import io
import json
from pathlib import Path
from typing import Any


CHAPTER_THEMES = [
    {"accent": "#1D4ED8", "soft": "#EFF6FF", "dark": False},  # 1 Intro
    {"accent": "#0F766E", "soft": "#F0FDFA", "dark": False},  # 2 KB Zoom 1
    {"accent": "#38BDF8", "soft": "#0B1324", "dark": True},   # 3 Audio Cinema
    {"accent": "#DB2777", "soft": "#FDF2F8", "dark": False},  # 4 Der-Die-Das
    {"accent": "#4338CA", "soft": "#EEF2FF", "dark": False},  # 5 Grammatik
    {"accent": "#0284C7", "soft": "#0C1829", "dark": True},   # 6 Phonetik Lab
    {"accent": "#B45309", "soft": "#FFFBEB", "dark": False},  # 7 AB Live Solver
    {"accent": "#059669", "soft": "#ECFDF5", "dark": False},  # 8 Rollenspiele
    {"accent": "#7C3AED", "soft": "#F5F3FF", "dark": False},  # 9 Satzbau
    {"accent": "#E11D48", "soft": "#FFF1F2", "dark": False},  # 10 Kultur/Fehler
    {"accent": "#0EA5E9", "soft": "#0B1324", "dark": True},   # 11 Turbo Sprechen
    {"accent": "#0D9488", "soft": "#F0FDFA", "dark": False},  # 12 Intensiv Recall
    {"accent": "#2563EB", "soft": "#EFF6FF", "dark": False},  # 13 Übersetzung
    {"accent": "#4F46E5", "soft": "#EEF2FF", "dark": False},  # 14 Wiederholung
    {"accent": "#F59E0B", "soft": "#090D1A", "dark": True},   # 15 Goethe Exam & Finale
]


def _encode_page_assets(assets_dir: Path | None, referenced_paths: set[str]) -> dict[str, str]:
    """Load referenced page JPEGs cleanly into compact base64 data URIs for standalone shard rendering."""
    catalog: dict[str, str] = {}
    if not assets_dir or not assets_dir.exists():
        return catalog

    try:
        from PIL import Image
    except Exception:
        Image = None  # type: ignore

    for rel in sorted(referenced_paths):
        if not rel:
            continue
        p = assets_dir / rel
        if not p.exists():
            continue
        try:
            raw = p.read_bytes()
            if Image is not None:
                with Image.open(io.BytesIO(raw)) as im:
                    if max(im.size) > 1200:
                        im = im.convert("RGB")
                        im.thumbnail((1200, 1200))
                        buf = io.BytesIO()
                        im.save(buf, format="JPEG", quality=84, optimize=True)
                        raw = buf.getvalue()
            mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
            catalog[rel] = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
        except Exception:
            continue
    return catalog


def build_menschen_stage_html(
    timeline_path: Path,
    assets_dir: Path | None,
    rms_path: Path,
    out_html: Path,
) -> Path:
    tl = json.loads(timeline_path.read_text(encoding="utf-8"))
    rms_data = json.loads(rms_path.read_text(encoding="utf-8"))

    ref_imgs: set[str] = set()
    for ev in tl.get("events", []):
        bd = ev.get("board_data") or {}
        if bd.get("page_img"):
            ref_imgs.add(str(bd["page_img"]))
    page_assets = _encode_page_assets(assets_dir, ref_imgs)

    tl_json = json.dumps(tl, ensure_ascii=False)
    rms_json = json.dumps(rms_data)
    assets_json = json.dumps(page_assets, ensure_ascii=False)
    themes_json = json.dumps(CHAPTER_THEMES)

    html_src = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8"/>
<title>{tl.get('course_title', 'Language Master Academy')}</title>
<style>
  :root {{
    --accent: #1D4ED8;
    --bg-stage: #F4F7FC;
    --ink: #0F172A;
    --muted: #475569;
    --card-bg: rgba(255, 255, 255, 0.94);
    --card-bd: rgba(15, 23, 42, 0.10);
    --der-c: #2563EB;
    --der-bg: #DBEAFE;
    --die-c: #DB2777;
    --die-bg: #FCE7F3;
    --das-c: #059669;
    --das-bg: #D1FAE5;
    --pl-c: #D97706;
    --pl-bg: #FEF3C7;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    width: 1920px; height: 1080px; overflow: hidden;
    font-family: 'Inter', 'Noto Sans Arabic', 'Amiri', 'Segoe UI', 'DejaVu Sans', system-ui, sans-serif;
    background: #0B1222; color: var(--ink);
  }}
  #bg-canvas {{
    position: fixed; inset: 0; width: 1920px; height: 1080px; z-index: 0; pointer-events: none;
  }}
  .stage-root {{
    position: relative; z-index: 2; width: 1920px; height: 1080px;
    display: flex; flex-direction: column;
  }}

  /* ── TOP HUD (62px) ── */
  .top-hud {{
    height: 62px; flex-shrink: 0;
    background: linear-gradient(90deg, #090F1E 0%, #111C38 55%, #0B1328 100%);
    color: #F8FAFC;
    display: flex; align-items: center; justify-content: space-between;
    padding: 0 26px;
    border-bottom: 2px solid rgba(56, 189, 248, 0.35);
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.32);
  }}
  .hud-left {{ display: flex; align-items: center; gap: 14px; }}
  .brand-pill {{
    background: linear-gradient(135deg, #F59E0B, #D97706);
    color: #0F172A; font-weight: 900; font-size: 13px; letter-spacing: 0.9px;
    padding: 6px 14px; border-radius: 999px;
  }}
  .lesson-tag {{
    font-size: 16px; font-weight: 800; color: #E2E8F0; letter-spacing: 0.2px;
  }}
  .de-meter-wrap {{
    display: flex; align-items: center; gap: 8px;
    background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.16);
    padding: 5px 12px; border-radius: 999px; font-size: 12px; font-weight: 800;
  }}
  .de-bar-track {{
    width: 72px; height: 8px; border-radius: 99px; background: rgba(255,255,255,0.16); overflow: hidden;
  }}
  .de-bar-fill {{
    height: 100%; background: linear-gradient(90deg, #38BDF8, #F59E0B); border-radius: 99px;
  }}
  .hud-center {{ display: flex; align-items: center; gap: 10px; }}
  .loc-pill {{
    background: rgba(56, 189, 248, 0.14); border: 1px solid rgba(56, 189, 248, 0.42);
    color: #7DD3FC; padding: 5px 14px; border-radius: 999px; font-size: 13px; font-weight: 700;
    max-width: 470px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  .ch-dots {{ display: flex; gap: 4px; align-items: center; }}
  .ch-dot {{
    width: 14px; height: 7px; border-radius: 4px; background: rgba(255,255,255,0.18);
    transition: all 0.2s;
  }}
  .ch-dot.done {{ background: #10B981; }}
  .ch-dot.active {{ width: 28px; background: #F59E0B; box-shadow: 0 0 8px #F59E0B; }}
  .hud-right {{ display: flex; align-items: center; gap: 14px; }}
  .eq-bars {{ display: flex; align-items: flex-end; gap: 3px; height: 22px; }}
  .eq-bar {{ width: 4px; border-radius: 2px; background: linear-gradient(180deg, #F59E0B, #38BDF8); height: 6px; }}
  .time-chip {{
    font-family: ui-monospace, Consolas, monospace; font-size: 15px; font-weight: 800;
    color: #FDE68A; background: rgba(255,255,255,0.08); padding: 5px 13px; border-radius: 8px;
  }}

  /* ── MAIN STAGE (1080 - 62 - 142 = 876px) ── */
  .main-area {{
    height: 876px; flex-shrink: 0;
    padding: 20px 26px;
    display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 22px;
    overflow: hidden;
  }}
  .main-area.full {{
    display: flex; align-items: center; justify-content: center;
  }}

  /* Left Visual Pane */
  .visual-pane {{
    position: relative; border-radius: 22px; overflow: hidden;
    background: var(--card-bg); border: 1.5px solid var(--card-bd);
    box-shadow: 0 18px 46px rgba(15, 23, 42, 0.14);
    display: flex; flex-direction: column;
  }}
  body.dark-mode .visual-pane {{
    background: rgba(12, 20, 38, 0.92);
    border-color: rgba(56, 189, 248, 0.25);
    color: #F8FAFC;
    box-shadow: 0 22px 54px rgba(0, 0, 0, 0.55);
  }}

  /* 3D Ken Burns Book Page Container */
  .kb-stage-3d {{
    position: relative; width: 100%; height: 100%; overflow: hidden;
    background: radial-gradient(circle at 50% 45%, #1E293B 0%, #090E1A 100%);
    display: flex; align-items: center; justify-content: center;
    perspective: 1400px;
  }}
  .kb-book-frame {{
    position: relative; width: 92%; height: 92%; overflow: hidden; border-radius: 14px;
    background: #FFFFFF;
    box-shadow: -14px 20px 55px rgba(0,0,0,0.58), 0 0 0 1px rgba(255,255,255,0.18);
    transform-style: preserve-3d;
  }}
  .kb-book-frame img {{
    width: 100%; height: 100%; object-fit: contain;
    transform-origin: center center;
  }}
  .kb-spotlight-ring {{
    position: absolute; pointer-events: none;
    border: 3px solid #F59E0B; border-radius: 16px;
    box-shadow: 0 0 0 9999px rgba(8, 13, 28, 0.28), 0 0 28px rgba(245, 158, 11, 0.65);
  }}
  .kb-page-ribbon {{
    position: absolute; top: 14px; left: 14px; z-index: 6;
    background: rgba(15, 23, 42, 0.88); color: #FDE68A;
    font-size: 13px; font-weight: 800; padding: 7px 14px; border-radius: 999px;
    border: 1px solid rgba(245, 158, 11, 0.55);
  }}
  .kb-fallback-page {{
    width: 100%; height: 100%; display: flex; flex-direction: column;
    align-items: center; justify-content: center; padding: 36px; text-align: center;
    background: linear-gradient(145deg, #FFFFFF, #EFF6FF); color: #0F172A;
  }}

  /* HUEBER AUDIO CINEMA */
  .audio-cinema-wrap {{
    width: 100%; height: 100%; padding: 24px;
    display: grid; grid-template-rows: auto 150px 1fr; gap: 16px;
    background: radial-gradient(circle at 20% 20%, rgba(14, 165, 233, 0.16), transparent 60%), #080E1E;
    color: #F8FAFC;
  }}
  .cinema-top-bar {{
    display: flex; align-items: center; justify-content: space-between;
  }}
  .cinema-badge {{
    display: inline-flex; align-items: center; gap: 10px;
    background: rgba(245, 158, 11, 0.18); border: 1px solid #F59E0B; color: #FDE68A;
    font-size: 14px; font-weight: 800; padding: 7px 16px; border-radius: 999px;
  }}
  .spec-bars-wrap {{
    background: rgba(255,255,255,0.04); border: 1px solid rgba(56,189,248,0.28);
    border-radius: 18px; padding: 16px 22px;
    display: flex; align-items: flex-end; justify-content: space-between; gap: 7px;
  }}
  .spec-bar {{
    flex: 1; border-radius: 6px 6px 2px 2px;
    background: linear-gradient(180deg, #F59E0B 0%, #38BDF8 55%, #1D4ED8 100%);
    min-height: 10px;
  }}
  .cinema-lower {{
    display: grid; grid-template-columns: 0.42fr 0.58fr; gap: 16px; min-height: 0;
  }}
  .cinema-thumb {{
    border-radius: 14px; overflow: hidden; background: #0F172A;
    border: 1px solid rgba(255,255,255,0.16); display: flex; align-items: center; justify-content: center;
  }}
  .cinema-thumb img {{ width: 100%; height: 100%; object-fit: contain; }}
  .transcript-glass {{
    background: rgba(15, 23, 42, 0.85); border: 1px solid rgba(148, 163, 184, 0.26);
    border-radius: 16px; padding: 18px 20px; overflow: hidden;
    display: flex; flex-direction: column; gap: 8px;
  }}
  .transcript-hdr {{ font-size: 13px; font-weight: 800; color: #38BDF8; letter-spacing: 0.8px; text-transform: uppercase; }}
  .transcript-body {{
    font-size: 17px; line-height: 1.55; color: #E2E8F0; white-space: pre-wrap; overflow: hidden;
  }}

  /* DER DIE DAS SCIENTIFIC COLOR STAGE */
  .ddd-wrap {{
    width: 100%; height: 100%; padding: 26px; display: flex; flex-direction: column;
    justify-content: space-between; gap: 16px;
    background: linear-gradient(160deg, #F8FAFC 0%, #EEF2FF 100%);
  }}
  .ddd-hero-card {{
    flex: 1; border-radius: 22px; padding: 28px 32px;
    display: flex; flex-direction: column; justify-content: space-between;
    box-shadow: 0 22px 48px rgba(15,23,42,0.12);
    border: 3px solid var(--der-c); background: #FFFFFF;
    transform: perspective(1200px) rotateX(1.5deg);
  }}
  .ddd-hero-card.art-der {{ border-color: var(--der-c); background: linear-gradient(145deg, #FFFFFF, #EFF6FF); }}
  .ddd-hero-card.art-die {{ border-color: var(--die-c); background: linear-gradient(145deg, #FFFFFF, #FDF2F8); }}
  .ddd-hero-card.art-das {{ border-color: var(--das-c); background: linear-gradient(145deg, #FFFFFF, #ECFDF5); }}
  .ddd-hero-card.art-pl, .ddd-hero-card.art-expr {{ border-color: var(--pl-c); background: linear-gradient(145deg, #FFFFFF, #FFFBEB); }}
  .ddd-hero-card.art-verb {{ border-color: #7C3AED; background: linear-gradient(145deg, #FFFFFF, #F5F3FF); }}
  .art-pill {{
    display: inline-flex; padding: 7px 16px; border-radius: 999px; font-size: 15px; font-weight: 900;
    color: #FFFFFF; background: var(--der-c); align-self: flex-start;
  }}
  .ddd-hero-card.art-die .art-pill {{ background: var(--die-c); }}
  .ddd-hero-card.art-das .art-pill {{ background: var(--das-c); }}
  .ddd-hero-card.art-pl .art-pill, .ddd-hero-card.art-expr .art-pill {{ background: var(--pl-c); }}
  .ddd-hero-card.art-verb .art-pill {{ background: #7C3AED; }}
  .ddd-word {{ font-size: 52px; font-weight: 900; color: #0F172A; letter-spacing: -0.6px; margin-top: 8px; }}
  .ddd-phon-row {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: center; margin-top: 8px; }}
  .ipa-chip {{
    font-family: ui-monospace, Consolas, monospace; font-size: 19px; font-weight: 700;
    background: #0F172A; color: #38BDF8; padding: 6px 14px; border-radius: 10px;
  }}
  .ar-pron-chip {{
    font-size: 21px; font-weight: 800; background: #FEF3C7; color: #92400E;
    padding: 6px 16px; border-radius: 10px; direction: rtl;
  }}
  .ddd-ar-meaning {{ font-size: 32px; font-weight: 900; color: #1E293B; direction: rtl; text-align: right; }}
  .ddd-sentence-box {{
    background: rgba(15, 23, 42, 0.05); border-radius: 14px; padding: 14px 18px;
    border-left: 5px solid #0F172A;
  }}
  .ddd-deck-strip {{
    display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px;
  }}
  .deck-mini {{
    background: #FFFFFF; border: 1.5px solid rgba(15,23,42,0.12); border-radius: 12px;
    padding: 10px 12px; font-size: 13px;
  }}
  .deck-mini.curr {{ border-color: #F59E0B; box-shadow: 0 0 0 2px rgba(245,158,11,0.35); background: #FFFBEB; }}

  /* GRAMMAR SYNTAX ENGINE */
  .gram-wrap {{
    width: 100%; height: 100%; padding: 18px 22px; display: flex; flex-direction: column;
    justify-content: space-between; gap: 10px; background: #FFFFFF;
  }}
  .gram-title {{ font-size: 21px; font-weight: 900; color: #1E3A8A; }}
  .gram-tbl {{ width: 100%; border-collapse: separate; border-spacing: 0 5px; }}
  .gram-tbl th {{
    text-align: left; padding: 8px 12px; background: #0F172A; color: #F8FAFC;
    font-size: 13.5px; font-weight: 800;
  }}
  .gram-tbl th:first-child {{ border-radius: 10px 0 0 10px; }}
  .gram-tbl th:last-child {{ border-radius: 0 10px 10px 0; }}
  .gram-tbl td {{
    padding: 9px 12px; background: #F8FAFC; font-size: 15.5px; font-weight: 700; color: #0F172A;
    border-top: 1px solid #E2E8F0; border-bottom: 1px solid #E2E8F0;
  }}
  .gram-tbl tr.active-row td {{
    background: linear-gradient(90deg, #DBEAFE, #FEF3C7);
    color: #0F172A; border-top: 2px solid #F59E0B; border-bottom: 2px solid #F59E0B;
    font-size: 16.5px;
  }}
  .satzbau-diagram {{
    display: grid; grid-template-columns: 1fr 1fr 1.4fr; gap: 10px;
    background: #0F172A; border-radius: 16px; padding: 12px 14px; color: #F8FAFC;
  }}
  .pos-box {{
    background: rgba(255,255,255,0.08); border: 1.5px solid rgba(56,189,248,0.35);
    border-radius: 12px; padding: 10px 14px; text-align: center;
  }}
  .pos-box.pos2 {{
    background: rgba(245, 158, 11, 0.22); border-color: #F59E0B;
  }}

  /* PHONETIK ARTICULATION LAB */
  .phon-wrap {{
    width: 100%; height: 100%; padding: 26px; display: flex; flex-direction: column;
    justify-content: space-between; gap: 16px;
    background: radial-gradient(circle at 80% 15%, rgba(56,189,248,0.18), transparent 55%), #091326;
    color: #F8FAFC;
  }}
  .phon-hero-row {{ display: flex; align-items: center; justify-content: space-between; gap: 18px; }}
  .phon-symbol-card {{
    background: rgba(56,189,248,0.12); border: 2px solid #38BDF8;
    border-radius: 20px; padding: 20px 28px; flex: 1;
  }}
  .speak-pulse {{
    background: linear-gradient(135deg, #F59E0B, #EA580C); color: #FFFFFF;
    font-size: 20px; font-weight: 900; padding: 16px 24px; border-radius: 16px;
    box-shadow: 0 0 28px rgba(245, 158, 11, 0.55); text-align: center;
  }}
  .phon-examples {{ display: flex; flex-wrap: wrap; gap: 12px; }}
  .phon-ex-pill {{
    background: rgba(255,255,255,0.09); border: 1px solid rgba(255,255,255,0.22);
    padding: 10px 18px; border-radius: 12px; font-size: 22px; font-weight: 800; color: #FDE68A;
  }}

  /* ARBEITSBUCH LIVE SOLVER */
  .ab-solver-wrap {{
    width: 100%; height: 100%; display: grid; grid-template-rows: 1fr auto;
    background: #111827; position: relative;
  }}
  .ab-solution-drawer {{
    background: linear-gradient(90deg, #064E3B 0%, #0F766E 100%);
    color: #ECFDF5; padding: 16px 22px; border-top: 3px solid #34D399;
    display: flex; align-items: center; justify-content: space-between; gap: 16px;
  }}

  /* RIGHT TEACHING NOTES PANE */
  .right-pane {{
    position: relative; border-radius: 22px; padding: 22px 24px;
    background: var(--card-bg); border: 1.5px solid var(--card-bd);
    box-shadow: 0 18px 46px rgba(15, 23, 42, 0.12);
    display: flex; flex-direction: column; justify-content: space-between; overflow: hidden;
  }}
  body.dark-mode .right-pane {{
    background: rgba(15, 23, 42, 0.90); border-color: rgba(56, 189, 248, 0.25); color: #F8FAFC;
  }}
  .micro-bar {{
    position: absolute; top: 0; left: 0; height: 5px;
    background: linear-gradient(90deg, #2563EB, #F59E0B);
  }}
  .meta-row {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; gap: 8px; }}
  .norm-tag {{
    background: #1E3A8A; color: #FFFFFF; font-size: 12.5px; font-weight: 800;
    padding: 5px 12px; border-radius: 999px;
  }}
  .page-ref-badge {{
    background: #FEF3C7; color: #92400E; font-size: 12.5px; font-weight: 800;
    padding: 5px 12px; border-radius: 999px;
  }}
  .slide-heading {{ font-size: 27px; font-weight: 900; line-height: 1.24; color: inherit; margin-bottom: 4px; }}
  .slide-subheading {{
    font-size: 17px; font-weight: 700; color: #0284C7; margin-bottom: 14px;
    direction: rtl; text-align: right;
  }}
  body.dark-mode .slide-subheading {{ color: #7DD3FC; }}
  .cards-stack {{ display: flex; flex-direction: column; gap: 10px; }}
  .info-card {{
    background: rgba(248, 250, 252, 0.92); border: 1.5px solid rgba(15, 23, 42, 0.10);
    border-radius: 14px; padding: 12px 15px; transition: all 0.2s;
  }}
  body.dark-mode .info-card {{
    background: rgba(30, 41, 59, 0.85); border-color: rgba(148, 163, 184, 0.20);
  }}
  .info-card.active {{
    border-color: #F59E0B; background: linear-gradient(90deg, #FFFBEB, #FFFFFF);
    box-shadow: 0 8px 24px rgba(245, 158, 11, 0.18); transform: translateX(-4px);
  }}
  body.dark-mode .info-card.active {{
    background: linear-gradient(90deg, rgba(245, 158, 11, 0.18), rgba(30, 41, 59, 0.95));
  }}
  .card-top {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 5px; gap: 8px; }}
  .card-title-ar {{
    font-size: 15.5px; font-weight: 900; color: inherit; direction: rtl;
    display: flex; align-items: center; gap: 8px;
  }}
  .num-dot {{
    width: 24px; height: 24px; border-radius: 50%; background: #1E3A8A; color: #FFFFFF;
    display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 900;
  }}
  .info-card.active .num-dot {{ background: #D97706; }}
  .card-ref {{ font-size: 11.5px; font-weight: 800; color: #64748B; }}
  .card-body {{ font-size: 15px; line-height: 1.48; direction: rtl; unicode-bidi: plaintext; text-align: right; color: inherit; }}
  .card-takeaway {{
    margin-top: 6px; font-size: 13px; font-weight: 800; color: #0F766E;
    direction: rtl; unicode-bidi: plaintext; text-align: right;
  }}
  body.dark-mode .card-takeaway {{ color: #34D399; }}
  .rule-banner {{
    background: linear-gradient(135deg, #0F172A, #1E3A8A); color: #FDE68A;
    border-radius: 14px; padding: 13px 16px; font-size: 15px; font-weight: 700;
    direction: rtl; unicode-bidi: plaintext; text-align: right; border: 1px solid rgba(245, 158, 11, 0.45);
  }}

  /* QUIZ & DIPLOMA FULLSCREEN */
  .quiz-stage {{
    width: 1560px; max-width: 94%; border-radius: 26px; padding: 34px 40px;
    background: rgba(15, 23, 42, 0.94); border: 2px solid rgba(56, 189, 248, 0.45);
    color: #F8FAFC; box-shadow: 0 28px 70px rgba(0, 0, 0, 0.65);
  }}
  .quiz-opts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 22px; }}
  .quiz-opt {{
    background: rgba(255, 255, 255, 0.06); border: 2px solid rgba(148, 163, 184, 0.25);
    border-radius: 16px; padding: 18px 22px; font-size: 22px; font-weight: 800;
    display: flex; align-items: center; gap: 14px;
  }}
  .quiz-opt.correct {{
    background: rgba(16, 185, 129, 0.22); border-color: #10B981; color: #A7F3D0;
    box-shadow: 0 0 26px rgba(16, 185, 129, 0.35);
  }}
  .diploma-stage {{
    width: 1520px; border-radius: 28px; padding: 38px 46px;
    background: radial-gradient(circle at top right, rgba(245, 158, 11, 0.22), transparent 55%), #0A1124;
    border: 3px solid #F59E0B; color: #F8FAFC; text-align: center;
    box-shadow: 0 32px 90px rgba(0, 0, 0, 0.72), inset 0 0 40px rgba(245, 158, 11, 0.14);
  }}

  /* ── BOTTOM DUAL CAPTION DECK (142px) ── */
  .footer-deck {{
    height: 142px; flex-shrink: 0;
    background: linear-gradient(180deg, #0B1328 0%, #050914 100%);
    border-top: 2px solid rgba(56, 189, 248, 0.35);
    padding: 10px 30px 12px; color: #F8FAFC;
    display: flex; flex-direction: column; justify-content: space-between;
  }}
  .footer-top-strip {{ display: flex; align-items: center; justify-content: space-between; gap: 14px; }}
  .sub-focus-pill {{
    background: rgba(245, 158, 11, 0.18); border: 1px solid rgba(245, 158, 11, 0.50);
    color: #FDE68A; font-size: 13px; font-weight: 800; padding: 4px 13px; border-radius: 999px;
  }}
  .sub-de-bar {{
    display: flex; align-items: center; justify-content: space-between; gap: 16px;
    background: rgba(255,255,255,0.06); border-radius: 10px; padding: 5px 14px;
  }}
  .sub-de-txt {{ font-size: 18px; font-weight: 800; color: #7DD3FC; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 980px; direction: ltr; unicode-bidi: embed; }}
  .sub-pron-txt {{ font-size: 16.5px; font-weight: 800; color: #FDE68A; direction: rtl; unicode-bidi: plaintext; white-space: nowrap; max-width: 780px; overflow: hidden; text-overflow: ellipsis; }}
  .sub-caption-live {{
    font-size: 21px; font-weight: 700; line-height: 1.35; color: #FFFFFF;
    text-align: center; direction: rtl; unicode-bidi: plaintext;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
</style>
</head>
<body>
<canvas id="bg-canvas" width="1920" height="1080"></canvas>
<div class="stage-root">
  <header class="top-hud">
    <div class="hud-left">
      <span class="brand-pill">LANGUAGE AKADEMIE</span>
      <span class="lesson-tag" id="lesson-title-hdr">{tl.get('course_title', 'Menschen')}</span>
      <div class="de-meter-wrap" title="German Immersion Ratio">
        <span>DE <strong id="de-pct-txt">{tl.get('de_pct', 20)}%</strong></span>
        <div class="de-bar-track"><div class="de-bar-fill" style="width:{tl.get('de_pct', 20)}%"></div></div>
      </div>
    </div>
    <div class="hud-center">
      <span class="loc-pill" id="loc-pill">Ch. 1/15</span>
      <div class="ch-dots" id="ch-dots"></div>
    </div>
    <div class="hud-right">
      <div class="eq-bars" id="eq-bars">
        <div class="eq-bar"></div><div class="eq-bar"></div><div class="eq-bar"></div>
        <div class="eq-bar"></div><div class="eq-bar"></div><div class="eq-bar"></div>
      </div>
      <span class="time-chip" id="time-chip">00:00:00 / 02:01:00</span>
    </div>
  </header>

  <main class="main-area" id="main-area"></main>

  <footer class="footer-deck">
    <div class="footer-top-strip">
      <span class="sub-focus-pill" id="sub-focus-pill">Kursbuch &amp; Arbeitsbuch</span>
      <span style="font-size:13px; color:#94A3B8; font-weight:700;" id="sub-ref-txt">Course Studio Series</span>
    </div>
    <div class="sub-de-bar">
      <span class="sub-de-txt" id="sub-de-txt">Willkommen!</span>
      <span class="sub-pron-txt" id="sub-pron-txt"></span>
    </div>
    <div class="sub-caption-live" id="sub-caption-live">أهلاً بكم في أكاديمية منشن الشاملة...</div>
  </footer>
</div>

<script>
const TL = {tl_json};
const RMS = {rms_json};
const PAGE_ASSETS = {assets_json};
const CH_THEMES = {themes_json};
const TOTAL_DUR = Number(TL.total_duration_sec || 7260);
const EVENTS = TL.events || [];

(function initDots() {{
  const wrap = document.getElementById("ch-dots");
  const totalCh = Math.max(15, (TL.chapters || []).length);
  for (let i = 1; i <= totalCh; i++) {{
    const d = document.createElement("div");
    d.className = "ch-dot";
    d.dataset.ch = String(i);
    wrap.appendChild(d);
  }}
}})();

function esc(s) {{
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}}

function fmtHMS(sec) {{
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return `${{String(h).padStart(2,'0')}}:${{String(m).padStart(2,'0')}}:${{String(r).padStart(2,'0')}}`;
}}

function findEventAt(tSec) {{
  if (!EVENTS.length) return {{}};
  let lo = 0, hi = EVENTS.length - 1;
  while (lo <= hi) {{
    const mid = (lo + hi) >> 1;
    const ev = EVENTS[mid];
    if (tSec < ev.start_sec) hi = mid - 1;
    else if (tSec >= ev.end_sec) lo = mid + 1;
    else return ev;
  }}
  return EVENTS[Math.min(EVENTS.length - 1, Math.max(0, lo))];
}}

function drawBackground(frameIdx, isDark) {{
  const c = document.getElementById("bg-canvas");
  const ctx = c.getContext("2d");
  if (isDark) {{
    ctx.fillStyle = "#080E1E";
    ctx.fillRect(0, 0, 1920, 1080);
    const g = ctx.createRadialGradient(
      960 + Math.sin(frameIdx * 0.015) * 260,
      460 + Math.cos(frameIdx * 0.012) * 140,
      40, 960, 500, 980
    );
    g.addColorStop(0, "rgba(56, 189, 248, 0.14)");
    g.addColorStop(1, "rgba(8, 14, 30, 0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 1920, 1080);
  }} else {{
    ctx.fillStyle = "#EEF2FA";
    ctx.fillRect(0, 0, 1920, 1080);
    ctx.strokeStyle = "rgba(30, 58, 138, 0.045)";
    ctx.lineWidth = 1;
    for (let x = 0; x < 1920; x += 64) {{
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, 1080); ctx.stroke();
    }}
    for (let y = 0; y < 1080; y += 64) {{
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(1920, y); ctx.stroke();
    }}
  }}
}}

function renderBookKenBurns(bd, progress, labelOverride) {{
  const src = PAGE_ASSETS[bd.page_img || ""] || "";
  const fb = bd.focus_box || {{ cx: 50, cy: 40, zoom: 1.35 }};
  const zoom = Number(fb.zoom || 1.35);
  const curZoom = (1.06 + (zoom - 1.06) * Math.min(1, progress * 1.35)).toFixed(3);
  const dx = ((50 - Number(fb.cx || 50)) * 0.45 * Math.min(1, progress * 1.4)).toFixed(2);
  const dy = ((50 - Number(fb.cy || 45)) * 0.45 * Math.min(1, progress * 1.4)).toFixed(2);
  const rotY = (-3.0 + progress * 2.2).toFixed(2);

  const imgHtml = src
    ? `<img src="${{src}}" style="transform: scale(${{curZoom}}) translate(${{dx}}%, ${{dy}}%);"/>`
    : `<div class="kb-fallback-page">
         <div style="font-size:15px;font-weight:800;color:#1D4ED8;margin-bottom:10px;">${{esc(bd.page_ref || "Kursbuch")}}</div>
         <div style="font-size:32px;font-weight:900;margin-bottom:12px;">${{esc(bd.heading || "")}}</div>
         <div style="font-size:19px;color:#475569;direction:rtl;">${{esc(bd.sub_heading || "")}}</div>
       </div>`;

  const spotTop = Math.max(10, Math.min(62, Number(fb.cy || 40) - 18));
  const spotLeft = Math.max(8, Math.min(48, Number(fb.cx || 50) - 34));

  return `
    <div class="kb-stage-3d">
      <div class="kb-page-ribbon">${{esc(labelOverride || bd.page_ref || "Seite")}} • Zoom ${{(curZoom * 100).toFixed(0)}}%</div>
      <div class="kb-book-frame" style="transform: rotateY(${{rotY}}deg);">
        ${{imgHtml}}
        <div class="kb-spotlight-ring" style="left:${{spotLeft}}%; top:${{spotTop}}%; width:68%; height:36%;"></div>
      </div>
    </div>`;
}}

function renderHueberCinema(ev, bd, frameIdx, rmsVal) {{
  const src = PAGE_ASSETS[bd.page_img || ""] || "";
  let bars = "";
  for (let i = 0; i < 32; i++) {{
    const wave = 0.45 + 0.55 * Math.abs(Math.sin(frameIdx * 0.28 + i * 0.48));
    const h = Math.max(10, Math.min(116, Math.round((rmsVal / 8.2) * wave)));
    bars += `<div class="spec-bar" style="height:${{h}}px;"></div>`;
  }}
  const thumb = src
    ? `<img src="${{src}}"/>`
    : `<div style="padding:18px;text-align:center;color:#94A3B8;font-weight:700;">${{esc(bd.page_ref || "Hueber Audio")}}</div>`;

  return `
    <div class="audio-cinema-wrap">
      <div class="cinema-top-bar">
        <span class="cinema-badge">🔊 AUTHENTIC ORIGINAL AUDIO • ${{esc(bd.page_ref || "CD Track")}}</span>
        <span style="font-size:14px;color:#38BDF8;font-weight:700;">استمع بتركيز ثم ردد في مرحلة التحدث</span>
      </div>
      <div class="spec-bars-wrap">${{bars}}</div>
      <div class="cinema-lower">
        <div class="cinema-thumb">${{thumb}}</div>
        <div class="transcript-glass">
          <div class="transcript-hdr">📜 Original-Transkript / النص السماعي الأصلي</div>
          <div class="transcript-body">${{esc(bd.transcript || ev.subtitle_de || "Hörtext — Listen carefully to German intonation.")}}</div>
        </div>
      </div>
    </div>`;
}}

function renderDerDieDas(bd) {{
  const vf = bd.vocab_focus || {{ de: bd.heading || "", art: "expr", pl: "—", ipa: "", ar_pron: "", ar: bd.sub_heading || "", ex_de: "", ex_ar: "" }};
  const art = String(vf.art || "expr").toLowerCase();
  const artBadge = {{
    der: "DER • مذكر (أزرق)",
    die: "DIE • مؤنث (وردي)",
    das: "DAS • محايد (أخضر)",
    plural: "DIE • جمع (برتقالي)",
    verb: "VERB • فعل (بنفسجي)",
    expr: "AUSDRUCK • تعبير تواصلي",
  }}[art] || "WORTSCHATZ";

  const deck = (bd.vocab_deck || [vf]).slice(0, 5);
  const deckHtml = deck.map(d => {{
    const isCurr = d.de === vf.de;
    return `<div class="deck-mini ${{isCurr ? 'curr' : ''}}">
      <div style="font-weight:900;color:#0F172A;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${{esc(d.de)}}</div>
      <div style="font-size:12px;color:#475569;direction:rtl;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${{esc(d.ar)}}</div>
    </div>`;
  }}).join("");

  return `
    <div class="ddd-wrap">
      <div class="ddd-hero-card art-${{esc(art)}}">
        <div>
          <span class="art-pill">${{esc(artBadge)}}</span>
          <div class="ddd-word">${{esc(vf.de)}}</div>
          <div class="ddd-phon-row">
            ${{vf.ipa ? `<span class="ipa-chip">${{esc(vf.ipa)}}</span>` : ""}}
            ${{vf.ar_pron ? `<span class="ar-pron-chip">النطق: ${{esc(vf.ar_pron)}}</span>` : ""}}
            ${{vf.pl && vf.pl !== "—" ? `<span style="background:#F1F5F9;padding:6px 14px;border-radius:10px;font-weight:800;">Plural: ${{esc(vf.pl)}}</span>` : ""}}
          </div>
        </div>
        <div class="ddd-ar-meaning">${{esc(vf.ar)}}</div>
        <div class="ddd-sentence-box">
          <div style="font-size:21px;font-weight:800;color:#0F172A;">🇩🇪 ${{esc(vf.ex_de || ev_sub_de_fallback)}}</div>
          <div style="font-size:18px;font-weight:700;color:#0F766E;direction:rtl;margin-top:4px;">🇲🇦 ${{esc(vf.ex_ar)}}</div>
        </div>
      </div>
      <div class="ddd-deck-strip">${{deckHtml}}</div>
    </div>`;
}}

function renderGrammarStage(bd) {{
  const gt = bd.grammar_table || {{ title: bd.heading || "Grammatik", headers: ["Form", "Beispiel", "Regel"], rows: [] }};
  const actIdx = Number(bd.active_row ?? -1);
  const ths = (gt.headers || []).map(h => `<th>${{esc(h)}}</th>`).join("");
  const trs = (gt.rows || []).map((row, ri) => {{
    const cls = ri === actIdx ? "active-row" : "";
    const tds = row.map(cell => `<td>${{esc(cell)}}</td>`).join("");
    return `<tr class="${{cls}}">${{tds}}</tr>`;
  }}).join("");

  return `
    <div class="gram-wrap">
      <div>
        <div class="gram-title">📐 ${{esc(gt.title)}}</div>
        <div style="font-size:15px;color:#475569;margin-top:4px;direction:rtl;text-align:right;">${{esc(gt.rule_ar || bd.rule_box || "")}}</div>
      </div>
      <div style="flex:1;overflow:hidden;">
        <table class="gram-tbl">
          <thead><tr>${{ths}}</tr></thead>
          <tbody>${{trs}}</tbody>
        </table>
      </div>
      <div class="satzbau-diagram">
        <div class="pos-box"><div style="font-size:11px;color:#94A3B8;">POSITION 1</div><div style="font-weight:800;margin-top:3px;">Subjekt / Fragewort</div></div>
        <div class="pos-box pos2"><div style="font-size:11px;color:#FDE68A;">POSITION 2 ⚡ (PFLICHT!)</div><div style="font-weight:900;color:#FDE68A;margin-top:3px;">KONJUGIERTES VERB</div></div>
        <div class="pos-box"><div style="font-size:11px;color:#94A3B8;">POSITION 3+</div><div style="font-weight:800;margin-top:3px;">Objekt / Ort / Zeit</div></div>
      </div>
    </div>`;
}}

function renderPhonetikLab(ev, bd, frameIdx, rmsVal) {{
  const ph = bd.phonetic || {{ symbol: bd.heading || "Deutsch Laute", ipa: bd.page_ref || "", ar_guide: bd.sub_heading || "", examples: [], tip: bd.rule_box || "" }};
  const exHtml = (ph.examples || []).map(x => `<span class="phon-ex-pill">${{esc(x)}}</span>`).join("");
  const isCountdown = ev.type === "countdown";
  const ringScale = (1.0 + (rmsVal / 1400)).toFixed(3);
  return `
    <div class="phon-wrap">
      <div class="phon-hero-row">
        <div class="phon-symbol-card">
          <div style="font-size:14px;font-weight:800;color:#38BDF8;">IPA: ${{esc(ph.ipa)}}</div>
          <div style="font-size:38px;font-weight:900;margin-top:4px;">${{esc(ph.symbol)}}</div>
        </div>
        <div class="speak-pulse" style="transform:scale(${{ringScale}});">
          ${{isCountdown ? "🎙️ دورك الآن! كرر بصوت واضح" : "👄 تدريب المخارج الألمانية"}}
        </div>
      </div>
      <div style="background:rgba(255,255,255,0.06);border-radius:16px;padding:18px 22px;direction:rtl;font-size:21px;font-weight:700;line-height:1.5;">
        ${{esc(ph.ar_guide)}}
      </div>
      <div>
        <div style="font-size:13px;color:#94A3B8;font-weight:800;margin-bottom:8px;">BEISPIELE ZUM NACHSPRECHEN:</div>
        <div class="phon-examples">${{exHtml}}</div>
      </div>
      <div style="background:rgba(16,185,129,0.16);border:1px solid #10B981;border-radius:14px;padding:12px 18px;direction:rtl;font-size:16px;font-weight:800;color:#A7F3D0;">
        💡 سر الإتقان: ${{esc(ph.tip)}}
      </div>
    </div>`;
}}

function renderArbeitsbuchSolver(bd, progress) {{
  const solTxt = bd.solution_text || bd.rule_box || "راجع دليل الحلول المعتمد لتمارين Arbeitsbuch.";
  const revealed = progress >= 0.35;
  return `
    <div class="ab-solver-wrap">
      ${{renderBookKenBurns(bd, progress, bd.page_ref || "Arbeitsbuch Seite")}}
      <div class="ab-solution-drawer" style="opacity:${{revealed ? 1 : 0.72}};">
        <div>
          <div style="font-size:12px;font-weight:800;color:#6EE7B7;">${{revealed ? "✓ OFFIZIELLE LÖSUNG ENTHÜLLT" : "⏳ فكّر في الإجابة قبل الكشف التلقائي..."}}</div>
          <div style="font-size:19px;font-weight:900;margin-top:3px;">${{esc(revealed ? solTxt : "اقرأ السؤال وحدد نوع الكلمة وموقع الفعل...")}}</div>
        </div>
        <span style="background:#10B981;color:#022C22;padding:8px 16px;border-radius:999px;font-weight:900;font-size:14px;">AB-Lösung</span>
      </div>
    </div>`;
}}

function renderDualDialogue(ev, bd) {{
  const spIsF = (ev.speaker || "lehrerin") === "lehrerin";
  return `
    <div style="width:100%;height:100%;padding:26px;display:flex;flex-direction:column;justify-content:space-between;background:linear-gradient(155deg,#ECFDF5,#FFFFFF);">
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <span style="background:#059669;color:#FFF;padding:7px 16px;border-radius:999px;font-weight:800;font-size:14px;">🎭 DIALOG &amp; ÜBERSETZUNG DE ↔ AR</span>
        <span style="font-weight:800;color:#0F766E;">المحادثة الثنائية الحية</span>
      </div>
      <div style="display:flex;flex-direction:column;gap:16px;">
        <div style="background:${{spIsF ? '#DBEAFE' : '#FFFFFF'}};border:2px solid #2563EB;border-radius:18px;padding:20px 24px;">
          <div style="font-size:13px;font-weight:900;color:#1D4ED8;margin-bottom:6px;">🇩🇪 DEUTSCHES ORIGINAL (Lehrerin Aoede &amp; Lehrer Charon)</div>
          <div style="font-size:32px;font-weight:900;color:#0F172A;">${{esc(ev.subtitle_de || bd.heading)}}</div>
          ${{ev.subtitle_pron ? `<div style="font-size:20px;font-weight:800;color:#B45309;margin-top:8px;direction:rtl;">النطق الميسر: ${{esc(ev.subtitle_pron)}}</div>` : ""}}
        </div>
        <div style="background:#0F172A;color:#F8FAFC;border-radius:18px;padding:20px 24px;direction:rtl;text-align:right;">
          <div style="font-size:13px;font-weight:800;color:#34D399;margin-bottom:6px;">🇲🇦 المعنى التواصلي الدقيق بالعربية:</div>
          <div style="font-size:27px;font-weight:800;line-height:1.45;">${{esc(ev.subtitle_ar || bd.sub_heading)}}</div>
        </div>
      </div>
      <div style="background:#FEF3C7;border-radius:12px;padding:12px 18px;color:#92400E;font-weight:800;direction:rtl;">
        🎙️ تدرّب على نبرة الصوت: الأسئلة مع W-Fragen تهبط في نهايتها، وأسئلة Ja/Nein ترتفع!
      </div>
    </div>`;
}}

function renderQuizArena(ev, bd, progress) {{
  const q = bd.quiz_state || {{}};
  const opts = q.options || [];
  const cidx = Number(q.correct_idx ?? 0);
  const reveal = Boolean(q.reveal);
  const letters = ["A", "B", "C", "D"];
  const optHtml = opts.map((o, i) => {{
    const ok = reveal && i === cidx;
    return `<div class="quiz-opt ${{ok ? 'correct' : ''}}">
      <span style="width:38px;height:38px;border-radius:50%;background:${{ok ? '#10B981' : '#334155'}};display:inline-flex;align-items:center;justify-content:center;">${{letters[i] || (i+1)}}</span>
      <span>${{esc(o)}}</span>
    </div>`;
  }}).join("");

  return `
    <div class="quiz-stage">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
        <span style="background:#F59E0B;color:#0F172A;font-weight:900;padding:6px 16px;border-radius:999px;">${{esc(bd.badge || "Goethe-Institut Simulation")}}</span>
        <span style="font-size:18px;font-weight:800;color:#38BDF8;">${{reveal ? "✓ التصحيح العلمي الرسمي" : "⏳ اختر الإجابة الصحيحة الآن"}}</span>
      </div>
      <div style="font-size:38px;font-weight:900;margin-bottom:8px;">${{esc(q.question_de || bd.heading)}}</div>
      <div style="font-size:21px;color:#7DD3FC;direction:rtl;text-align:right;">${{esc(q.context_ar || bd.sub_heading)}}</div>
      <div class="quiz-opts">${{optHtml}}</div>
      <div style="margin-top:22px;background:rgba(255,255,255,0.07);border-radius:14px;padding:16px 20px;direction:rtl;font-size:19px;font-weight:700;color:#FDE68A;">
        💡 ${{esc(bd.rule_box || "")}}
      </div>
    </div>`;
}}

function renderDiploma(bd) {{
  return `
    <div class="diploma-stage">
      <div style="font-size:16px;font-weight:900;letter-spacing:2.5px;color:#F59E0B;margin-bottom:12px;">MASTER AKADEMIE • ZERTIFIKAT</div>
      <div style="font-size:48px;font-weight:900;margin-bottom:10px;">${{esc(bd.heading || "Herzlichen Glückwunsch!")}}</div>
      <div style="font-size:23px;color:#7DD3FC;margin-bottom:26px;direction:rtl;">${{esc(bd.sub_heading || "")}}</div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-bottom:26px;text-align:right;">
        <div style="background:rgba(255,255,255,0.06);border:1px solid rgba(56,189,248,0.35);border-radius:16px;padding:18px;direction:rtl;">
          <div style="font-weight:900;color:#38BDF8;font-size:18px;">📘 فيديو + كتابا الدرس</div>
          <div style="margin-top:6px;font-size:15px;">تغطية كاملة لأكثر من ساعتين (KB + AB + صوتيات Hueber)</div>
        </div>
        <div style="background:rgba(255,255,255,0.06);border:1px solid rgba(245,158,11,0.45);border-radius:16px;padding:18px;direction:rtl;">
          <div style="font-weight:900;color:#FDE68A;font-size:18px;">📝 كتاب التمارين PDF</div>
          <div style="margin-top:6px;font-size:15px;">45 سؤالاً متدرجاً باللغة الألمانية والعربية مع الحل الكامل</div>
        </div>
        <div style="background:rgba(255,255,255,0.06);border:1px solid rgba(16,185,129,0.45);border-radius:16px;padding:18px;direction:rtl;">
          <div style="font-weight:900;color:#34D399;font-size:18px;">🎧 بودكاست التشريب MP3</div>
          <div style="margin-top:6px;font-size:15px;">تثبيت سمعي ونطقي متواصل في كل مكان دون نت!</div>
        </div>
      </div>
      <div style="font-size:20px;font-weight:800;color:#34D399;direction:rtl;">${{esc(bd.rule_box || "إلى الدرس الموالي!")}}</div>
    </div>`;
}}

let ev_sub_de_fallback = "";

window.renderAtTimeAsync = function(tSec, frameIdx) {{
  const ev = findEventAt(tSec);
  const chNum = Math.max(1, Number(ev.chapter_num || 1));
  const theme = CH_THEMES[(chNum - 1) % CH_THEMES.length];
  const isDark = Boolean(theme.dark) || ev.board_mode === "HUEBER_AUDIO_CINEMA" || ev.board_mode === "INTERACTIVE_DRILL_ARENA" || ev.board_mode === "FINALE_DIPLOMA_STAGE";
  document.body.className = isDark ? "dark-mode" : "";
  drawBackground(frameIdx, isDark);

  document.getElementById("time-chip").textContent = `${{fmtHMS(tSec)}} / ${{fmtHMS(TOTAL_DUR)}}`;
  document.getElementById("loc-pill").textContent = `Ch.${{chNum}}/15 • ${{ev.chapter_title || ""}}`;

  document.querySelectorAll(".ch-dot").forEach(el => {{
    const n = Number(el.dataset.ch);
    el.className = "ch-dot" + (n < chNum ? " done" : (n === chNum ? " active" : ""));
  }});

  const rmsVal = Number(RMS[Math.min(RMS.length - 1, Math.max(0, frameIdx))] || 220);
  document.querySelectorAll(".eq-bar").forEach((bar, i) => {{
    const h = Math.max(4, Math.min(22, Math.round((rmsVal / 40) * (0.65 + 0.4 * Math.sin(frameIdx * 0.42 + i)))));
    bar.style.height = `${{h}}px`;
  }});

  const dur = Math.max(0.5, Number(ev.dur_sec || 10));
  const progress = Math.max(0, Math.min(1, (tSec - Number(ev.start_sec || 0)) / dur));
  const bd = ev.board_data || {{}};
  const cards = bd.cards || [];
  const activeCardIdx = cards.length ? Math.min(cards.length - 1, Math.floor(progress * cards.length)) : 0;

  ev_sub_de_fallback = ev.subtitle_de || "";
  document.getElementById("sub-focus-pill").textContent = `📌 ${{bd.badge || ev.chapter_title || ""}}`;
  document.getElementById("sub-ref-txt").textContent = bd.page_ref || "Language Studio";
  document.getElementById("sub-de-txt").textContent = ev.subtitle_de || bd.heading || "";
  document.getElementById("sub-pron-txt").textContent = ev.subtitle_pron ? `النطق: ${{ev.subtitle_pron}}` : (ev.subtitle_ar || "");

  const cues = ev.caption_cues || [];
  let activeCaption = ev.subtitle_ar || ev.narration_fr || "";
  for (const cue of cues) {{
    if (tSec >= cue.start && tSec <= cue.end) {{ activeCaption = cue.text; break; }}
  }}
  document.getElementById("sub-caption-live").textContent = activeCaption;

  const mainEl = document.getElementById("main-area");
  const mode = ev.board_mode || "BOOK_KEN_BURNS_SPOTLIGHT";

  if (mode === "INTERACTIVE_DRILL_ARENA") {{
    mainEl.className = "main-area full";
    mainEl.innerHTML = renderQuizArena(ev, bd, progress);
    return;
  }}
  if (mode === "FINALE_DIPLOMA_STAGE") {{
    mainEl.className = "main-area full";
    mainEl.innerHTML = renderDiploma(bd);
    return;
  }}

  mainEl.className = "main-area";
  let leftHtml = "";
  if (mode === "HUEBER_AUDIO_CINEMA") leftHtml = renderHueberCinema(ev, bd, frameIdx, rmsVal);
  else if (mode === "DER_DIE_DAS_COLOR_STAGE") leftHtml = renderDerDieDas(bd);
  else if (mode === "GRAMMAR_SYNTAX_ENGINE") leftHtml = renderGrammarStage(bd);
  else if (mode === "PHONETIK_ARTICULATION_LAB") leftHtml = renderPhonetikLab(ev, bd, frameIdx, rmsVal);
  else if (mode === "ARBEITSBUCH_LIVE_SOLVER") leftHtml = renderArbeitsbuchSolver(bd, progress);
  else if (mode === "DIALOGUE_DUAL_IMMERSION") leftHtml = renderDualDialogue(ev, bd);
  else leftHtml = renderBookKenBurns(bd, progress, "");

  const cardsHtml = cards.map((c, idx) => {{
    const st = idx === activeCardIdx ? "active" : "";
    return `
      <div class="info-card ${{st}}">
        <div class="card-top">
          <div class="card-title-ar"><span class="num-dot">${{idx + 1}}</span><span>${{esc(c.title)}}</span></div>
          ${{c.ref ? `<span class="card-ref">${{esc(c.ref)}}</span>` : ""}}
        </div>
        <div class="card-body">${{esc(c.detail)}}</div>
        ${{c.takeaway ? `<div class="card-takeaway">★ ${{esc(c.takeaway)}}</div>` : ""}}
      </div>`;
  }}).join("");

  mainEl.innerHTML = `
    <section class="visual-pane">${{leftHtml}}</section>
    <section class="right-pane">
      <div class="micro-bar" style="width:${{(progress * 100).toFixed(1)}}%;"></div>
      <div>
        <div class="meta-row">
          <span class="norm-tag">${{esc(bd.badge || "Deutsch-Arabisch")}}</span>
          <span class="page-ref-badge">${{esc(bd.page_ref || "Menschen")}}</span>
        </div>
        <div class="slide-heading">${{esc(bd.heading || "")}}</div>
        <div class="slide-subheading">${{esc(bd.sub_heading || "")}}</div>
        <div class="cards-stack">${{cardsHtml}}</div>
      </div>
      <div class="rule-banner">💡 قاعدة ذهبية: ${{esc(bd.rule_box || "")}}</div>
    </section>`;
}};
</script>
</body>
</html>"""

    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html_src, encoding="utf-8")
    print(f"LANG_STAGE_BUILT: events={len(tl.get('events', []))} embedded_pages={len(page_assets)} size_kb={out_html.stat().st_size / 1024:.1f} -> {out_html}", flush=True)
    return out_html


def main() -> None:
    parser = argparse.ArgumentParser(description="Build 1920x1080 Ken Burns + 3D CSS UX HTML5 Stage for Menschen")
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, default=None)
    parser.add_argument("--rms", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    build_menschen_stage_html(args.timeline, args.assets_dir, args.rms, args.out)


if __name__ == "__main__":
    main()
