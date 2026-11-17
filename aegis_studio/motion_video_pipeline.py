"""AI Engaging Storytelling & Motion-Graphics Studio (Multi-Layout Visuals + Multi-Voice TTS + Soundbed)."""

from __future__ import annotations

import argparse
import html as html_lib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any

from .aegis_client import AegisStudioClient
from .ass_subtitles import SubtitleSegment, write_ass_file
from .ffmpeg_utils import (
    best_h264_video_flags,
    escape_ffmpeg_filter_path,
    get_ffmpeg_exe,
    mix_audio_with_subtle_bed_and_sfx,
    probe_media_info,
    save_tts_audio_normalized,
)

PALETTES = [
    {"bg1": "#070B19", "bg2": "#0F172A", "accent": "#38BDF8", "accent2": "#A855F7", "gold": "#FBBF24"},
    {"bg1": "#061518", "bg2": "#0A2328", "accent": "#10B981", "accent2": "#06B6D4", "gold": "#FDE68A"},
    {"bg1": "#150919", "bg2": "#210F2B", "accent": "#F472B6", "accent2": "#818CF8", "gold": "#FCD34D"},
    {"bg1": "#110F07", "bg2": "#1D180A", "accent": "#F59E0B", "accent2": "#EF4444", "gold": "#FEF08A"},
]


def _is_rtl_text(text: str) -> bool:
    return bool(re.search(r"[\u0600-\u06FF]", text or ""))


def _sanitize_inline_svg(svg_raw: str) -> str:
    """Allow safe vector artwork while stripping any script/event attributes."""
    s = (svg_raw or "").strip()
    if "<svg" not in s.lower():
        return ""
    s = re.sub(r"<script[\s\S]*?</script>", "", s, flags=re.I)
    s = re.sub(r"\son\w+\s*=\s*(['\"]).*?\1", "", s, flags=re.I)
    m = re.search(r"<svg[\s\S]*?</svg>", s, flags=re.I)
    return m.group(0) if m else ""


def _build_scene_html(scene: dict[str, Any], scene_idx: int, total_scenes: int, width: int, height: int) -> str:
    """Build deterministic high-retention 1080p/vertical motion layout driven by window.__setTime."""
    pal = PALETTES[scene_idx % len(PALETTES)]
    layout = str(scene.get("layout") or "visual_diagram").lower().strip()
    kicker = html_lib.escape(str(scene.get("kicker") or f"CHAPTER {scene_idx + 1:02d}"))
    title = html_lib.escape(str(scene.get("title") or ""))
    subtitle = html_lib.escape(str(scene.get("subtitle") or ""))
    speaker = html_lib.escape(str(scene.get("voice_name") or "Charon"))
    narration = str(scene.get("narration_script") or "")
    rtl = _is_rtl_text(f"{title} {subtitle} {narration}")
    dir_attr = "rtl" if rtl else "ltr"
    cards = list(scene.get("cards") or [])[:4]

    cards_html_parts: list[str] = []
    for ci, card in enumerate(cards):
        if isinstance(card, str):
            c_metric, c_lbl, c_det = f"0{ci + 1}", card, ""
        else:
            c_metric = html_lib.escape(str(card.get("metric") or f"0{ci + 1}"))
            c_lbl = html_lib.escape(str(card.get("label") or ""))
            c_det = html_lib.escape(str(card.get("detail") or ""))
        vs_badge = "<div class='vs-pill'>VS</div>" if (layout == "versus_comparison" and ci == 0 and len(cards) >= 2) else ""
        step_cls = "timeline-card" if layout == "timeline_flow" else ""
        cards_html_parts.append(
            f"""
            <div class="m-card {step_cls}" data-stagger="{ci}">
              {vs_badge}
              <div class="m-metric">{c_metric}</div>
              <div class="m-label">{c_lbl}</div>
              <div class="m-detail">{c_det}</div>
            </div>"""
        )
    cards_html = "\n".join(cards_html_parts)

    safe_svg = _sanitize_inline_svg(str(scene.get("svg_graphic") or ""))
    if not safe_svg:
        safe_svg = f"""
        <svg viewBox="0 0 360 360" class="hero-svg">
          <defs>
            <linearGradient id="g{scene_idx}" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="{pal['accent']}"/>
              <stop offset="100%" stop-color="{pal['accent2']}"/>
            </linearGradient>
          </defs>
          <circle cx="180" cy="180" r="142" fill="none" stroke="url(#g{scene_idx})" stroke-width="4" stroke-dasharray="18 12" class="spin-slow"/>
          <circle cx="180" cy="180" r="102" fill="rgba(255,255,255,0.03)" stroke="{pal['gold']}" stroke-width="2" opacity="0.75"/>
          <polygon points="180,62 276,228 84,228" fill="none" stroke="url(#g{scene_idx})" stroke-width="4.5" stroke-linejoin="round"/>
          <circle cx="180" cy="180" r="16" fill="{pal['gold']}"/>
        </svg>"""

    is_vertical = height > width
    is_centered = layout in ("hook_impact", "spotlight_quote")
    grid_cols = "minmax(0, 1fr)" if (is_vertical or is_centered) else "minmax(0, 1.38fr) minmax(0, 0.82fr)"
    if is_vertical or layout == "timeline_flow":
        card_cols = "minmax(0, 1fr)"
    elif len(cards) == 3:
        card_cols = "repeat(3, minmax(0, 1fr))"
    elif len(cards) >= 2:
        card_cols = "minmax(0, 1fr) minmax(0, 1fr)"
    else:
        card_cols = "minmax(0, 1fr)"
    title_sz = "64px" if layout == "hook_impact" else ("52px" if is_vertical else "54px")

    return f"""<!DOCTYPE html>
<html lang="{'ar' if rtl else 'en'}" dir="ltr">
<head>
<meta charset="utf-8" />
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --accent: {pal['accent']};
    --accent2: {pal['accent2']};
    --gold: {pal['gold']};
  }}
  html, body {{
    width: {width}px; height: {height}px; overflow: hidden;
    background: {pal['bg1']};
    font-family: 'Cairo', 'Noto Sans Arabic', 'Segoe UI', 'DejaVu Sans', sans-serif;
    color: #F8FAFC;
    position: relative;
  }}
  .bg-canvas {{
    position: fixed; inset: 0; overflow: hidden; z-index: 0;
    background: radial-gradient(circle at 18% 20%, {pal['bg2']} 0%, {pal['bg1']} 72%);
  }}
  .ambient-orb {{
    position: absolute; border-radius: 50%; opacity: 0.28; pointer-events: none;
  }}
  .orb-a {{
    width: 680px; height: 680px; top: -180px; left: -140px;
    background: radial-gradient(circle, var(--accent) 0%, transparent 68%);
  }}
  .orb-b {{
    width: 720px; height: 720px; bottom: -210px; right: -160px;
    background: radial-gradient(circle, var(--accent2) 0%, transparent 68%);
  }}
  .grid-overlay {{
    position: absolute; inset: 0;
    background-image: linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
                      linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
    background-size: 64px 64px;
    mask-image: radial-gradient(circle at center, black 40%, transparent 95%);
  }}
  .stage {{
    position: relative; z-index: 2; width: 100%; height: 100%;
    padding: {'88px 54px 240px' if is_vertical else '82px 76px 175px'};
    display: grid; grid-template-columns: {grid_cols}; gap: 38px; align-items: center;
  }}
  .text-col {{
    min-width: 0; display: flex; flex-direction: column; gap: 18px;
    {'align-items: center; text-align: center;' if is_centered else ''}
  }}
  .top-chips {{ display: flex; align-items: center; gap: 12px; opacity: 0; transform: translateY(18px); }}
  .kicker {{
    display: inline-flex; align-items: center; gap: 8px;
    padding: 8px 18px; border-radius: 999px;
    background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.18);
    color: var(--gold); font-weight: 800; font-size: 17px; letter-spacing: 0.04em;
  }}
  .speaker-chip {{
    padding: 7px 14px; border-radius: 999px;
    background: rgba(56, 189, 248, 0.14); border: 1px solid rgba(56, 189, 248, 0.35);
    color: var(--accent); font-weight: 800; font-size: 15px;
  }}
  h1 {{
    font-size: {title_sz}; line-height: 1.24; font-weight: 900; max-width: {'1200px' if is_centered else '100%'};
    overflow-wrap: break-word;
    background: linear-gradient(120deg, #FFFFFF 35%, var(--accent) 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    opacity: 0; transform: translateY(26px);
  }}
  .sub-lead {{
    font-size: {'25px' if is_vertical else '25px'}; line-height: 1.5; color: #CBD5E1; font-weight: 600;
    max-width: {'980px' if is_centered else '100%'}; overflow-wrap: break-word;
    opacity: 0; transform: translateY(24px);
  }}
  .cards-grid {{
    display: grid; grid-template-columns: {card_cols}; gap: 18px; margin-top: 6px; width: 100%;
    max-width: {'1250px' if is_centered else '100%'}; text-align: start;
  }}
  .m-card {{
    min-width: 0; position: relative; background: rgba(15, 23, 42, 0.88); border: 1px solid rgba(255,255,255,0.14);
    border-radius: 20px; padding: 18px 22px; box-shadow: 0 18px 40px rgba(0,0,0,0.35);
    opacity: 0; transform: translateY(32px) scale(0.96);
  }}
  .timeline-card {{ border-inline-start: 5px solid var(--accent); }}
  .vs-pill {{
    position: absolute; top: 50%; inset-inline-end: -22px; transform: translateY(-50%); z-index: 4;
    background: var(--gold); color: #090D16; font-weight: 900; font-size: 15px;
    padding: 6px 10px; border-radius: 999px; box-shadow: 0 6px 16px rgba(0,0,0,0.45);
  }}
  .m-metric {{ font-size: 26px; font-weight: 900; color: var(--accent); margin-bottom: 4px; }}
  .m-label {{ font-size: 21px; font-weight: 800; color: #F8FAFC; margin-bottom: 4px; }}
  .m-detail {{ font-size: 17px; line-height: 1.45; color: #94A3B8; }}
  .visual-col {{
    {'display: none;' if is_centered else 'display: flex;'}
    min-width: 0; align-items: center; justify-content: center;
    background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.1);
    border-radius: 30px; padding: 28px; min-height: {'260px' if is_vertical else '430px'};
    opacity: 0; transform: scale(0.92);
  }}
  .visual-col svg {{ width: 100%; max-width: 360px; height: auto; }}
  .hud-bar {{
    position: fixed; left: 72px; right: 72px; top: 24px; z-index: 5;
    display: flex; align-items: center; gap: 18px;
  }}
  .hud-track {{ flex: 1; height: 7px; background: rgba(255,255,255,0.12); border-radius: 99px; overflow: hidden; }}
  .hud-fill {{ height: 100%; width: 0%; background: linear-gradient(90deg, var(--accent), var(--gold)); }}
  .hud-badge {{ font-size: 15px; font-weight: 800; color: #94A3B8; white-space: nowrap; }}
</style>
</head>
<body>
  <div class="bg-canvas">
    <div class="ambient-orb orb-a"></div>
    <div class="ambient-orb orb-b"></div>
    <div class="grid-overlay"></div>
  </div>

  <div class="hud-bar">
    <div class="hud-badge">AEGIS NEXUS STUDIO · {scene_idx + 1}/{total_scenes}</div>
    <div class="hud-track"><div class="hud-fill" id="el-prog"></div></div>
  </div>

  <div class="stage" dir="{dir_attr}">
    <div class="text-col">
      <div class="top-chips" id="el-kicker">
        <div class="kicker"><span>◆</span><span>{kicker}</span></div>
        <div class="speaker-chip">🎙 {speaker}</div>
      </div>
      <h1 id="el-title">{title}</h1>
      <div class="sub-lead" id="el-sub">{subtitle}</div>
      <div class="cards-grid">{cards_html}</div>
    </div>
    <div class="visual-col" id="el-visual">{safe_svg}</div>
  </div>

<script>
  function easeOutCubic(x) {{
    const c = Math.max(0, Math.min(1, x));
    return 1 - Math.pow(1 - c, 3);
  }}
  function reveal(el, t, startSec, spanSec, extraScale) {{
    if (!el) return;
    const p = easeOutCubic((t - startSec) / spanSec);
    el.style.opacity = String(p);
    const dy = (1 - p) * 26;
    const sc = extraScale ? (0.94 + 0.06 * p) : 1;
    el.style.transform = `translateY(${{dy.toFixed(2)}}px) scale(${{sc.toFixed(4)}})`;
  }}
  window.__setTime = function(t, dur) {{
    const ratio = dur > 0 ? Math.max(0, Math.min(1, t / dur)) : 1;
    const outP = dur > 1.0 && t > (dur - 0.22) ? Math.max(0.25, (dur - t) / 0.22) : 1;
    document.body.style.opacity = String(outP);

    reveal(document.getElementById('el-kicker'), t, 0.04, 0.42, false);
    reveal(document.getElementById('el-title'), t, 0.12, 0.50, false);
    reveal(document.getElementById('el-sub'), t, 0.24, 0.50, false);
    reveal(document.getElementById('el-visual'), t, 0.16, 0.60, true);

    const cards = document.querySelectorAll('.m-card');
    cards.forEach((c, idx) => reveal(c, t, 0.36 + idx * 0.20, 0.45, true));

    const oa = document.querySelector('.orb-a');
    const ob = document.querySelector('.orb-b');
    if (oa) oa.style.transform = `translate(${{(Math.sin(t * 0.9) * 28).toFixed(1)}}px, ${{(Math.cos(t * 0.7) * 22).toFixed(1)}}px)`;
    if (ob) ob.style.transform = `translate(${{(Math.cos(t * 0.8) * 30).toFixed(1)}}px, ${{(Math.sin(t * 0.6) * 24).toFixed(1)}}px)`;

    const spin = document.querySelector('.spin-slow');
    if (spin) {{
      spin.style.transformOrigin = '180px 180px';
      spin.style.transform = `rotate(${{(t * 28).toFixed(2)}}deg)`;
    }}

    const prog = document.getElementById('el-prog');
    if (prog) prog.style.width = `${{(ratio * 100).toFixed(2)}}%`;
  }};
  window.__setTime(0, 1);
</script>
</body>
</html>"""


def generate_storyboard_via_aegis(
    client: AegisStudioClient,
    topic: str,
    language: str = "العربية",
    scene_count: int = 4,
    voice_default: str = "Charon",
    style_mode: str = "storytelling",
) -> list[dict[str, Any]]:
    """Use AEGIS Quality Mix to direct an engaging, high-retention multi-layout video storyboard."""
    sys_p = (
        "You are an elite YouTube documentary showrunner & motion-graphics director.\n"
        "Craft punchy hooks, engaging storytelling, expressive dialogue turns, sharp stat cards, and crisp SVG metaphors.\n"
        "Output STRICT JSON only."
    )
    alt_voice = "Aoede" if voice_default != "Aoede" else "Puck"
    cast_note = (
        f'Use a dynamic 2-host cast alternating `voice_name` between "{voice_default}" and "{alt_voice}"!'
        if style_mode in ("dialogue", "storytelling")
        else f'Use `voice_name`: "{voice_default}".'
    )
    user_p = f"""Create a vivid, highly engaging {scene_count}-scene video storyboard in {language} about:
"{topic}"

Engagement & Variety Rules:
- Scene 1 MUST use `layout: "hook_impact"` with an intriguing curiosity hook question or striking fact!
- Subsequent scenes rotate layouts creatively across: `"visual_diagram"`, `"versus_comparison"`, `"timeline_flow"`, `"spotlight_quote"`.
- {cast_note}
- Each `narration_script` must sound natural, lively, and concise (~28-55 words, 10-18s spoken).
- Cards (2-3 per scene): sharp metric/number/keyword + concise label + crisp micro-insight.
- Include custom minimalist vector `<svg viewBox="0 0 360 360">...</svg>` in `svg_graphic` for visual scenes (no `<script>` tags).

Return JSON format:
{{
  "scenes": [
    {{
      "scene_id": 1,
      "layout": "hook_impact",
      "kicker": "HOOK",
      "title": "...",
      "subtitle": "...",
      "voice_name": "{voice_default}",
      "narration_script": "...",
      "cards": [{{"metric": "01", "label": "...", "detail": "..."}}],
      "svg_graphic": "<svg viewBox='0 0 360 360'>...</svg>"
    }}
  ]
}}"""
    res = client.generate_json(sys_p, user_p, max_output_tokens=16384, thinking_budget=2048, temperature=0.4)
    scenes = list(res["data"].get("scenes") or [])
    if not scenes:
        raise RuntimeError(f"Storyboard returned 0 scenes: {res}")
    print(f"[DIRECTOR] Built {len(scenes)} engaging scenes via {res.get('model')}", flush=True)
    return scenes


def _render_scene_video_stream(
    page: Any,
    html_str: str,
    out_mp4: Path,
    ass_path: Path | None,
    width: int,
    height: int,
    fps: int,
    duration_sec: float,
    force_cpu: bool = False,
) -> Path:
    """Capture deterministic Chromium motion frames piped straight into FFmpeg (silent clip, master audio mixed afterward)."""
    exe = get_ffmpeg_exe()
    total_frames = max(int(math.ceil(duration_sec * fps)), fps)
    page.set_content(html_str, wait_until="domcontentloaded")

    vf_parts: list[str] = [f"scale={width}:{height}:flags=lanczos"]
    if ass_path and ass_path.exists():
        vf_parts.append(f"ass='{escape_ffmpeg_filter_path(ass_path)}'")

    cmd = [
        exe, "-y",
        "-f", "image2pipe", "-vcodec", "mjpeg", "-framerate", str(fps), "-i", "pipe:0",
        "-vf", ",".join(vf_parts),
        "-t", f"{duration_sec:.3f}",
        *best_h264_video_flags("cinema", force_cpu=force_cpu),
        "-an",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    stderr_log = out_mp4.with_suffix(".ffmpeg.log")
    with stderr_log.open("wb") as err_fh:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err_fh)
        assert proc.stdin is not None
        try:
            for f_idx in range(total_frames):
                t_sec = f_idx / float(fps)
                page.evaluate("([t, d]) => window.__setTime(t, d)", [t_sec, duration_sec])
                frame_bytes = page.screenshot(type="jpeg", quality=92)
                proc.stdin.write(frame_bytes)
            proc.stdin.close()
        except BrokenPipeError:
            pass
        ret = proc.wait()
    if ret != 0:
        err_tail = stderr_log.read_text(encoding="utf-8", errors="ignore")[-500:] if stderr_log.exists() else ""
        raise RuntimeError(f"FFmpeg pipe render failed ({ret}): {err_tail}")
    stderr_log.unlink(missing_ok=True)
    return out_mp4


def _split_narration_to_captions(text: str, total_dur: float) -> list[SubtitleSegment]:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?؟،;:\n])\s+", text.strip()) if s.strip()]
    if not sentences:
        sentences = [text.strip()]
    weights = [max(1, len(s.split())) for s in sentences]
    w_sum = sum(weights)
    segs: list[SubtitleSegment] = []
    cur = 0.05
    usable = max(0.8, total_dur - 0.15)
    for idx, (sent, w) in enumerate(zip(sentences, weights), start=1):
        span = usable * (w / w_sum)
        segs.append(SubtitleSegment(index=idx, start=cur, end=cur + span, text=sent))
        cur += span
    return segs


def run_motion_video_pipeline(
    topic: str | None = None,
    storyboard_file: Path | None = None,
    out_dir: Path = Path("output/motion"),
    language: str = "العربية",
    scene_count: int = 4,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    voice_default: str = "Charon",
    style_mode: str = "storytelling",
    with_captions: bool = True,
    with_sfx: bool = True,
    force_cpu: bool = False,
    client: AegisStudioClient | None = None,
) -> dict[str, Any]:
    """Generate storyboard, multi-voice AEGIS TTS + SFX soundbed, and animated 1080p MP4 + Podcast MP3."""
    from playwright.sync_api import sync_playwright

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    aegis = client or AegisStudioClient()

    if storyboard_file and Path(storyboard_file).exists():
        raw_sb = json.loads(Path(storyboard_file).read_text(encoding="utf-8"))
        scenes = list(raw_sb.get("scenes") if isinstance(raw_sb, dict) else raw_sb)
    else:
        if not topic:
            raise ValueError("Either --topic or --storyboard must be provided.")
        scenes = generate_storyboard_via_aegis(
            aegis, topic, language=language, scene_count=scene_count, voice_default=voice_default, style_mode=style_mode
        )

    (out_dir / "storyboard.json").write_text(json.dumps({"scenes": scenes}, ensure_ascii=False, indent=2), encoding="utf-8")

    # 1. Synthesize multi-voice narration via AEGIS Free TTS
    scene_assets: list[dict[str, Any]] = []
    narration_timeline: list[tuple[float, Path]] = []
    cum_start = 0.0
    for i, sc in enumerate(scenes):
        sid = int(sc.get("scene_id") or (i + 1))
        voice = str(sc.get("voice_name") or voice_default)
        script = str(sc.get("narration_script") or sc.get("title") or "").strip()
        audio_mp3 = work_dir / f"scene_{sid:03d}.mp3"
        raw_audio, _mime, tts_model = aegis.synthesize_tts(script, voice_name=voice)
        save_tts_audio_normalized(raw_audio, audio_mp3)
        raw_dur = float(probe_media_info(audio_mp3)["duration"] or 4.0)
        clip_dur = raw_dur + (0.25 if i < len(scenes) - 1 else 0.15)

        ass_p: Path | None = None
        if with_captions and script:
            caps = _split_narration_to_captions(script, max(0.9, raw_dur))
            preset = "shorts" if height > width else "educational"
            ass_p = write_ass_file(caps, work_dir / f"scene_{sid:03d}.ass", video_width=width, video_height=height, preset=preset)

        narration_timeline.append((cum_start, audio_mp3))
        scene_assets.append({"sid": sid, "scene": sc, "audio": audio_mp3, "ass": ass_p, "duration": clip_dur, "tts_model": tts_model})
        cum_start += clip_dur
        print(f"[TTS] Scene {sid:02d}/{len(scenes)} ({tts_model}, {voice}) -> {raw_dur:.2f}s", flush=True)

    # 2. Mix cohesive soundtrack (voices + optional scene transition whoosh + warm ducked harmonic pad)
    master_audio_mp3 = out_dir / "podcast_audio_master.mp3"
    mix_audio_with_subtle_bed_and_sfx(narration_timeline, cum_start, master_audio_mp3, enable_sfx=with_sfx)

    # 3. Render deterministic motion scenes via Playwright Chromium -> FFmpeg pipe
    clips: list[Path] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        for idx, item in enumerate(scene_assets):
            clip_mp4 = work_dir / f"clip_{item['sid']:03d}.mp4"
            html_str = _build_scene_html(item["scene"], idx, len(scene_assets), width, height)
            _render_scene_video_stream(
                page,
                html_str,
                clip_mp4,
                item["ass"],
                width,
                height,
                fps,
                item["duration"],
                force_cpu=force_cpu,
            )
            clips.append(clip_mp4)
            print(f"[RENDER] Scene clip {idx + 1}/{len(scene_assets)} ({fps}fps {width}x{height}) complete", flush=True)
        browser.close()

    # 4. Concatenate silent video streams and mux cohesive master audio track
    exe = get_ffmpeg_exe()
    silent_concat = work_dir / "silent_concat.mp4"
    if len(clips) == 1:
        silent_concat = clips[0]
    else:
        concat_txt = work_dir / "concat.txt"
        concat_txt.write_text("\n".join(f"file '{c.resolve().as_posix()}'" for c in clips), encoding="utf-8")
        subprocess.run(
            [exe, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-c", "copy", str(silent_concat)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )

    final_mp4 = out_dir / "motion_studio_master.mp4"
    subprocess.run(
        [
            exe, "-y", "-i", str(silent_concat), "-i", str(master_audio_mp3),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
            str(final_mp4),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )

    final_info = probe_media_info(final_mp4)
    return {
        "video": str(final_mp4),
        "audio_podcast_mp3": str(master_audio_mp3),
        "storyboard": str(out_dir / "storyboard.json"),
        "scenes": len(clips),
        "fps": fps,
        "resolution": f"{width}x{height}",
        "duration_sec": round(float(final_info["duration"] or 0.0), 2),
        "client_mode": aegis.mode,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AEGIS-Native Engaging Motion-Graphics & Audio Studio")
    parser.add_argument("--topic", help="Topic or prompt to direct and animate")
    parser.add_argument("--storyboard", type=Path, help="Optional pre-built storyboard.json")
    parser.add_argument("--out-dir", type=Path, default=Path("output/motion"))
    parser.add_argument("--lang", default="العربية")
    parser.add_argument("--scenes", type=int, default=4)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--voice", default="Charon")
    parser.add_argument("--style", default="storytelling", choices=["storytelling", "dialogue", "solo"])
    parser.add_argument("--no-captions", action="store_true")
    parser.add_argument("--no-sfx", action="store_true", help="Disable subtle ambient pad & transition whoosh SFX")
    parser.add_argument("--force-cpu", action="store_true")
    args = parser.parse_args()

    res = run_motion_video_pipeline(
        topic=args.topic,
        storyboard_file=args.storyboard,
        out_dir=args.out_dir,
        language=args.lang,
        scene_count=args.scenes,
        width=args.width,
        height=args.height,
        fps=args.fps,
        voice_default=args.voice,
        style_mode=args.style,
        with_captions=not args.no_captions,
        with_sfx=not args.no_sfx,
        force_cpu=args.force_cpu,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
