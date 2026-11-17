"""Blender 3D Japanese Educational Video Prototype — Orchestrator (TTS + Glass Cards + Shards + FFmpeg).

Combines:
  1. Bilingual Arabic + Japanese neural TTS (`gemini-3.8-flash-tts`) + warm studio pad
  2. High-DPI RTL-accurate frosted glass card textures rendered via Headless Chromium
  3. 4-shard parallel Blender Cycles CPU frame encoding & seamless FFmpeg final assembly
"""

from __future__ import annotations

import argparse
import html
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

from aegis_studio.aegis_client import AegisStudioClient
from aegis_studio.ffmpeg_utils import (
    best_h264_video_flags,
    get_ffmpeg_exe,
    mix_audio_with_subtle_bed_and_sfx,
    probe_media_info,
    save_tts_audio_normalized,
)

DEFAULT_JP_CARDS: list[dict[str, Any]] = [
    {
        "id": "jp_sakura",
        "word_jp": "桜",
        "kana": "さくら",
        "romaji": "Sakura",
        "arabic_pron": "سَاكُورَا",
        "pitch": "L-H-L",
        "meaning_ar": "زهرة الكرز اليابانية — رمز الربيع والجمال العابر",
        "example_jp": "春にきれいな桜が咲きます。",
        "example_ar": "تتفتّح أزهار الكرز الجميلة في فصل الربيع.",
        "accent_hex": "#FF6B8B",
        "voice_name": "Aoede",
        "narration": (
            "الكلمة الأولى هي ساكورا، وتعني زهرة الكرز اليابانية. "
            "لاحظ ارتفاع النبرة في الوسط: سَا-كُوو-را. "
            "مثال: هارُو ني كِيرِي نَا ساكورا غَا ساكِيماس."
        ),
    },
    {
        "id": "jp_arigato",
        "word_jp": "ありがとう",
        "kana": "ありがとう",
        "romaji": "Arigatō",
        "arabic_pron": "أَرِيغَاتُوو",
        "pitch": "L-H-L-L-L",
        "meaning_ar": "شكراً جزيلاً — تعبير الامتنان اليومي المهذب",
        "example_jp": "いつも手伝ってくれてありがとう。",
        "example_ar": "شكراً لك دائماً على مساعدتك اللطيفة.",
        "accent_hex": "#F59E0B",
        "voice_name": "Charon",
        "narration": (
            "التعبير الثاني هو أريغاتو، ويعني شكراً جزيلاً في المحادثة اليومية. "
            "النطق الصوتي الممدود: أَرِي-غَا-تُوو. "
            "مثال: إيتسومو تِتسوداتّي كُورِتي أريغاتو."
        ),
    },
    {
        "id": "jp_nihongo",
        "word_jp": "日本語",
        "kana": "にほんご",
        "romaji": "Nihongo",
        "arabic_pron": "نِيهُونْغُو",
        "pitch": "L-H-H-H",
        "meaning_ar": "اللغة اليابانية — بوابة الثقافة والمعرفة",
        "example_jp": "毎日日本語を話します。",
        "example_ar": "أتحدّث اللغة اليابانية كل يوم.",
        "accent_hex": "#38BDF8",
        "voice_name": "Aoede",
        "narration": (
            "الكلمة الثالثة هي نيهونغو، أي اللغة اليابانية. "
            "ترتفع النبرة وتستمر مستوية: نِي-هُو-نْ-غُو. "
            "مثال: ماينِيتشي نيهونغو أو هاناشيماس."
        ),
    },
]


def _maybe_generate_cards_via_ai(topic: str) -> list[dict[str, Any]]:
    """Use Gemini when --topic is supplied and quota permits; fall back cleanly to defaults."""
    if not topic.strip():
        return [dict(c) for c in DEFAULT_JP_CARDS]
    try:
        client = AegisStudioClient()
        sys_p = (
            "You are a Japanese-Arabic linguistics professor. Return ONLY strict JSON "
            "containing 3 concise Japanese vocabulary cards for a 3D motion graphics video."
        )
        user_p = f"""Topic: {topic}
Return JSON: {{"cards": [3 objects]}} where each object has:
id, word_jp (max 6 chars, kanji/kana), kana, romaji, arabic_pron (Arabic phonetic script),
pitch (like "L-H-L"), meaning_ar (concise Arabic translation), example_jp, example_ar,
accent_hex ("#FF6B8B" or "#F59E0B" or "#38BDF8"), voice_name ("Aoede" or "Charon"),
narration (20-30 spoken Arabic+Japanese words explaining pronunciation and example)."""
        res = client.generate_json(sys_p, user_p, max_output_tokens=4096, thinking_budget=1024, temperature=0.3)
        cards = (res.get("data") or {}).get("cards") or []
        if len(cards) == 3 and all(c.get("word_jp") and c.get("narration") for c in cards):
            return cards
    except Exception as exc:
        print(f"[BLENDER_JP] AI topic generation skipped ({exc}); using curated Japanese cards.", flush=True)
    return [dict(c) for c in DEFAULT_JP_CARDS]


def _card_html_template(card: dict[str, Any], index: int, total: int) -> str:
    accent = str(card.get("accent_hex") or "#38BDF8")
    pitch_chips = "".join(
        f'<span class="p-step {"hi" if ch.strip().upper() == "H" else "lo"}">{html.escape(ch.strip().upper())}</span>'
        for ch in str(card.get("pitch") or "L-H").split("-")
        if ch.strip()
    )
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8" />
<style>
  @import url('https://fonts.googleapis.com/css2?family=Cairo:wght@600;700;800&family=Noto+Sans+JP:wght@600;800&display=swap');
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    width: 1024px; height: 1120px; overflow: hidden;
    background: transparent;
    font-family: 'Cairo', 'Noto Sans Arabic', 'DejaVu Sans', sans-serif;
  }}
  .glass {{
    width: 100%; height: 100%;
    border-radius: 44px;
    background: linear-gradient(155deg, rgba(16, 22, 38, 0.94), rgba(10, 14, 24, 0.96));
    border: 4px solid rgba(255, 255, 255, 0.16);
    box-shadow: inset 0 0 60px rgba(255, 255, 255, 0.04);
    padding: 48px 50px;
    display: flex; flex-direction: column; justify-content: space-between;
    color: #F8FAFC;
    position: relative;
  }}
  .top-bar {{
    display: flex; justify-content: space-between; align-items: center;
    direction: ltr;
  }}
  .act-pill {{
    background: {accent}22; border: 2px solid {accent};
    color: {accent}; border-radius: 999px; padding: 10px 26px;
    font-size: 24px; font-weight: 800; letter-spacing: 0.06em;
  }}
  .pitch-wrap {{ display: flex; gap: 10px; align-items: center; }}
  .p-step {{
    width: 44px; height: 44px; border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 22px; font-weight: 800;
  }}
  .p-step.hi {{ background: {accent}; color: #0B0F1A; transform: translateY(-6px); }}
  .p-step.lo {{ background: rgba(255,255,255,0.12); color: #CBD5E1; transform: translateY(4px); }}
  .jp-block {{
    text-align: center; padding: 24px 18px;
    background: rgba(255,255,255,0.04);
    border: 2px solid rgba(255,255,255,0.09);
    border-radius: 28px;
  }}
  .word-jp {{
    font-family: 'Noto Sans JP', 'Noto Sans CJK JP', 'IPAPGothic', 'DejaVu Sans', sans-serif;
    font-size: 92px; font-weight: 800; color: #FFFFFF; line-height: 1.15;
  }}
  .kana-row {{
    margin-top: 10px; font-size: 34px; color: {accent}; font-weight: 700;
    direction: ltr;
  }}
  .pron-box {{
    background: linear-gradient(90deg, {accent}26, rgba(255,255,255,0.04));
    border-right: 8px solid {accent};
    border-radius: 22px; padding: 22px 28px;
  }}
  .pron-label {{ font-size: 22px; color: #94A3B8; font-weight: 700; margin-bottom: 6px; }}
  .pron-ar {{ font-size: 46px; font-weight: 800; color: #FEF08A; }}
  .meaning-box {{
    font-size: 34px; font-weight: 700; line-height: 1.45; color: #E2E8F0;
    padding: 10px 6px;
  }}
  .example-box {{
    background: rgba(2, 6, 23, 0.62);
    border: 2px solid rgba(255,255,255,0.10);
    border-radius: 24px; padding: 24px 28px;
  }}
  .ex-jp {{
    font-family: 'Noto Sans JP', 'Noto Sans CJK JP', 'IPAPGothic', sans-serif;
    font-size: 32px; font-weight: 700; color: #FFFFFF;
    direction: ltr; text-align: left; margin-bottom: 10px;
  }}
  .ex-ar {{ font-size: 28px; color: #CBD5E1; font-weight: 600; }}
</style>
</head>
<body>
  <div class="glass">
    <div class="top-bar">
      <div class="act-pill">SCENE {index}/{total} • PITCH</div>
      <div class="pitch-wrap">{pitch_chips}</div>
    </div>
    <div class="jp-block">
      <div class="word-jp">{html.escape(str(card['word_jp']))}</div>
      <div class="kana-row">{html.escape(str(card['kana']))} &nbsp;•&nbsp; {html.escape(str(card['romaji']))}</div>
    </div>
    <div class="pron-box">
      <div class="pron-label">النطق الصوتي بالعربي</div>
      <div class="pron-ar">{html.escape(str(card['arabic_pron']))}</div>
    </div>
    <div class="meaning-box">{html.escape(str(card['meaning_ar']))}</div>
    <div class="example-box">
      <div class="ex-jp">{html.escape(str(card['example_jp']))}</div>
      <div class="ex-ar">{html.escape(str(card['example_ar']))}</div>
    </div>
  </div>
</body>
</html>
"""


def render_glass_card_textures(cards: list[dict[str, Any]], tex_dir: Path) -> list[Path]:
    """Render transparent RGBA glass card textures cleanly via Playwright Chromium."""
    from playwright.sync_api import sync_playwright

    tex_dir.mkdir(parents=True, exist_ok=True)
    out_paths: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1024, "height": 1120}, device_scale_factor=1)
        for idx, card in enumerate(cards, start=1):
            html_str = _card_html_template(card, idx, len(cards))
            page.set_content(html_str, wait_until="domcontentloaded")
            page.evaluate("() => document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()")
            out_png = tex_dir / f"card_{idx:02d}.png"
            page.screenshot(path=str(out_png), omit_background=True)
            out_paths.append(out_png)
        browser.close()
    return out_paths


def partition_frame_ranges(total_frames: int, total_shards: int) -> list[tuple[int, int]]:
    """Split 1-based inclusive frame range across N shards without gaps or overlap."""
    if total_frames < 1 or total_shards < 1:
        raise ValueError("total_frames and total_shards must be >= 1")
    ranges: list[tuple[int, int]] = []
    base, rem = divmod(total_frames, total_shards)
    cur = 1
    for s in range(total_shards):
        span = base + (1 if s < rem else 0)
        if span <= 0:
            continue
        ranges.append((cur, cur + span - 1))
        cur += span
    return ranges


def prepare_blender_bundle(
    work_dir: Path,
    topic: str = "",
    width: int = 1280,
    height: int = 720,
    fps: int = 24,
    samples: int = 16,
    dry_run: bool = False,
) -> Path:
    """Synthesize audio, render glass card PNGs, and write Blender scene manifest."""
    work_dir.mkdir(parents=True, exist_ok=True)
    cards = _maybe_generate_cards_via_ai(topic)

    audio_dir = work_dir / "clips"
    audio_dir.mkdir(parents=True, exist_ok=True)
    client = None if dry_run else AegisStudioClient()

    narration_wavs: list[tuple[float, Path]] = []
    card_durations: list[float] = []
    t_cursor = 0.0
    gap = 0.35

    for idx, card in enumerate(cards, start=1):
        clip_mp3 = audio_dir / f"act_{idx:02d}.mp3"
        if dry_run or client is None:
            exe = get_ffmpeg_exe()
            subprocess.run(
                [exe, "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=2.0", "-c:a", "libmp3lame", str(clip_mp3)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        else:
            raw_bytes, _mime, _model = client.synthesize_tts(
                str(card["narration"]),
                voice_name=str(card.get("voice_name") or "Aoede"),
            )
            save_tts_audio_normalized(raw_bytes, clip_mp3)

        dur = max(2.0, float(probe_media_info(clip_mp3)["duration"] or 3.0))
        narration_wavs.append((t_cursor, clip_mp3))
        card_durations.append(dur)
        t_cursor += dur + gap

    total_sec = max(6.0, t_cursor + 0.6)
    master_mp3 = work_dir / "master_audio.mp3"
    mix_audio_with_subtle_bed_and_sfx(narration_wavs, total_sec, master_mp3, enable_sfx=True)

    tex_dir = work_dir / "textures"
    png_paths = render_glass_card_textures(cards, tex_dir)

    total_frames = max(24, int(math.ceil(total_sec * fps)))
    acts: list[dict[str, Any]] = []
    cur_f = 1
    acc_t = 0.0
    for idx, (card, dur, png_p) in enumerate(zip(cards, card_durations, png_paths)):
        acc_t += dur + (gap if idx < len(cards) - 1 else 0.6)
        end_f = total_frames if idx == len(cards) - 1 else min(total_frames, max(cur_f + 12, int(round(acc_t * fps))))
        acts.append({
            "act_index": idx + 1,
            "start_frame": cur_f,
            "end_frame": end_f,
            "word_jp": card["word_jp"],
            "kana": card["kana"],
            "romaji": card["romaji"],
            "pitch": card["pitch"],
            "accent_hex": card.get("accent_hex") or "#38BDF8",
            "card_png": str(Path("textures") / png_p.name),
        })
        cur_f = end_f + 1

    manifest = {
        "width": int(width),
        "height": int(height),
        "fps": int(fps),
        "samples": int(samples),
        "total_duration_sec": round(total_sec, 2),
        "total_frames": total_frames,
        "master_audio": "master_audio.mp3",
        "acts": acts,
    }
    manifest_p = work_dir / "manifest.json"
    manifest_p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"BLENDER_JP_PREPARE_OK: acts={len(acts)} frames={total_frames} dur={total_sec:.2f}s -> {manifest_p}",
        flush=True,
    )
    return manifest_p


def encode_shard_mp4(frames_dir: Path, start_frame: int, fps: int, out_mp4: Path) -> Path:
    """Encode sequential Blender PNG frames into H.264 shard video cleanly."""
    exe = get_ffmpeg_exe()
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe, "-y",
        "-framerate", str(fps),
        "-start_number", str(start_frame),
        "-i", str(frames_dir / "frame_%06d.png"),
        *best_h264_video_flags("cinema", force_cpu=True),
        str(out_mp4),
    ]
    subprocess.run(cmd, check=True)
    print(f"BLENDER_JP_SHARD_ENCODED: {out_mp4}", flush=True)
    return out_mp4


def merge_shards_and_audio(shards_dir: Path, audio_mp3: Path, out_mp4: Path, previews_dir: Path) -> Path:
    """Concatenate H.264 shards + mux normalized master audio + grab act previews."""
    import re as _re

    exe = get_ffmpeg_exe()
    shards = sorted(
        shards_dir.glob("shard_*.mp4"),
        key=lambda p: (int(m.group(1)) if (m := _re.search(r"(\d+)", p.stem)) else 0, p.name),
    )
    if not shards:
        raise FileNotFoundError(f"No shard_*.mp4 found in {shards_dir}")

    concat_txt = out_mp4.parent / "shards_concat.txt"
    concat_txt.write_text("\n".join(f"file '{s.resolve().as_posix()}'" for s in shards), encoding="utf-8")

    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            exe, "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
            "-i", str(audio_mp3),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(out_mp4),
        ],
        check=True,
    )
    info = probe_media_info(out_mp4)

    previews_dir.mkdir(parents=True, exist_ok=True)
    dur = max(3.0, float(info["duration"] or 6.0))
    for i, frac in enumerate((0.15, 0.50, 0.82), start=1):
        ts = dur * frac
        subprocess.run(
            [exe, "-y", "-ss", f"{ts:.2f}", "-i", str(out_mp4), "-frames:v", "1", str(previews_dir / f"preview_act_{i}.png")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )

    print(
        f"BLENDER_JP_MERGE_OK: {out_mp4} dur={info['duration']:.2f}s res={info['width']}x{info['height']} shards={len(shards)}",
        flush=True,
    )
    return out_mp4


def main() -> None:
    parser = argparse.ArgumentParser(description="Blender 3D Japanese Prototype Pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_prep = sub.add_parser("prepare")
    p_prep.add_argument("--work-dir", type=Path, required=True)
    p_prep.add_argument("--topic", default="")
    p_prep.add_argument("--width", type=int, default=1280)
    p_prep.add_argument("--height", type=int, default=720)
    p_prep.add_argument("--fps", type=int, default=24)
    p_prep.add_argument("--samples", type=int, default=16)
    p_prep.add_argument("--dry-run", action="store_true")

    p_range = sub.add_parser("shard-range")
    p_range.add_argument("--manifest", type=Path, required=True)
    p_range.add_argument("--shard", type=int, required=True)
    p_range.add_argument("--total-shards", type=int, required=True)

    p_enc = sub.add_parser("encode-shard")
    p_enc.add_argument("--frames-dir", type=Path, required=True)
    p_enc.add_argument("--start-frame", type=int, required=True)
    p_enc.add_argument("--fps", type=int, default=24)
    p_enc.add_argument("--out", type=Path, required=True)

    p_merge = sub.add_parser("merge")
    p_merge.add_argument("--shards-dir", type=Path, required=True)
    p_merge.add_argument("--audio", type=Path, required=True)
    p_merge.add_argument("--out", type=Path, required=True)
    p_merge.add_argument("--previews-dir", type=Path, required=True)

    args = parser.parse_args()
    if args.cmd == "prepare":
        prepare_blender_bundle(args.work_dir, args.topic, args.width, args.height, args.fps, args.samples, args.dry_run)
    elif args.cmd == "shard-range":
        m = json.loads(args.manifest.read_text(encoding="utf-8"))
        ranges = partition_frame_ranges(int(m["total_frames"]), args.total_shards)
        lo, hi = ranges[args.shard - 1]
        print(f"{lo} {hi}")
    elif args.cmd == "encode-shard":
        encode_shard_mp4(args.frames_dir, args.start_frame, args.fps, args.out)
    elif args.cmd == "merge":
        merge_shards_and_audio(args.shards_dir, args.audio, args.out, args.previews_dir)


if __name__ == "__main__":
    main()
