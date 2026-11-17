"""Playwright Smart-Step Shard Renderer & Merger for Language Master Studio (2+ Hours @ 1080p24).

Adaptive smart-stepping renders smooth high-FPS motion during Hueber Audio Cinema spectrums,
Ken Burns zoom entries, Arbeitsbuch solution reveals, card spotlights, and speaking drills,
while merging N parallel cloud shards into a seamless constant-framerate 1920x1080 MP4.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PUBLIC_WORKER_ROOT = ROOT.parent / "aegis_cloud_render_public"
if _PUBLIC_WORKER_ROOT.exists() and str(_PUBLIC_WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(_PUBLIC_WORKER_ROOT))

from aegis_studio.ffmpeg_utils import get_ffmpeg_exe, probe_media_info

CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--allow-file-access-from-files",
]


def pick_smoke_timestamps(timeline: dict[str, Any]) -> list[tuple[str, float]]:
    targets = [
        ("01_book_ken_burns_spotlight", "BOOK_KEN_BURNS_SPOTLIGHT", 0.55),
        ("02_hueber_audio_cinema", "HUEBER_AUDIO_CINEMA", 0.45),
        ("03_der_die_das_colors", "DER_DIE_DAS_COLOR_STAGE", 0.50),
        ("04_grammar_syntax", "GRAMMAR_SYNTAX_ENGINE", 0.50),
        ("05_phonetik_lab", "PHONETIK_ARTICULATION_LAB", 0.50),
        ("06_arbeitsbuch_solver", "ARBEITSBUCH_LIVE_SOLVER", 0.65),
        ("07_dialogue_dual", "DIALOGUE_DUAL_IMMERSION", 0.50),
        ("08_goethe_exam_arena", "INTERACTIVE_DRILL_ARENA", 0.55),
        ("09_diploma_finale", "FINALE_DIPLOMA_STAGE", 0.50),
    ]
    picked: list[tuple[str, float]] = []
    evs = timeline.get("events", [])
    used: set[str] = set()
    for label, mode, frac in targets:
        for ev in evs:
            if ev.get("board_mode") == mode and ev["event_id"] not in used:
                if label == "08_goethe_exam_arena" and not ((ev.get("board_data") or {}).get("quiz_state") or {}).get("reveal"):
                    continue
                if label == "06_arbeitsbuch_solver" and not (ev.get("board_data") or {}).get("solution_text"):
                    continue
                used.add(ev["event_id"])
                mid = float(ev["start_sec"]) + frac * float(ev.get("dur_sec", 4.0))
                picked.append((label, round(mid, 3)))
                break
    return picked


def render_smoke_previews(stage_html: Path, timeline_path: Path, out_dir: Path, fps: int = 24) -> list[Path]:
    from playwright.sync_api import sync_playwright

    tl = json.loads(timeline_path.read_text(encoding="utf-8"))
    samples = pick_smoke_timestamps(tl)
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page.goto(stage_html.resolve().as_uri(), wait_until="load")
        page.evaluate("() => document.fonts ? document.fonts.ready : Promise.resolve()")
        for label, t_sec in samples:
            fidx = int(round(t_sec * fps))
            page.evaluate("([t, f]) => window.renderAtTimeAsync(t, f)", [t_sec, fidx])
            out_png = out_dir / f"{label}.png"
            page.screenshot(path=str(out_png), type="png", animations="disabled")
            rendered.append(out_png)
        browser.close()
    print(f"LANG_SMOKE_PREVIEWS: count={len(rendered)} dir={out_dir}", flush=True)
    return rendered


def _compute_high_motion_windows(timeline: dict[str, Any], fps: int) -> list[tuple[int, int]]:
    """Use dense FPS during countdowns, Hueber audio cinema spectrums, transitions, and AB reveals."""
    raw: list[tuple[int, int]] = []
    for ev in timeline.get("events", []):
        s_f = int(round(float(ev.get("start_sec", 0.0)) * fps))
        e_f = int(round(float(ev.get("end_sec", 0.0)) * fps))
        mode = ev.get("board_mode", "")
        if ev.get("type") in ("countdown", "audio_track") or mode == "HUEBER_AUDIO_CINEMA":
            raw.append((s_f, e_f))
            continue
        raw.append((s_f, min(e_f, s_f + int(1.6 * fps))))
        if mode == "ARBEITSBUCH_LIVE_SOLVER" and e_f > s_f:
            rev_f = s_f + int(0.35 * (e_f - s_f))
            raw.append((max(s_f, rev_f - 4), min(e_f, rev_f + int(0.9 * fps))))
        cards = (ev.get("board_data") or {}).get("cards") or []
        if len(cards) > 1 and e_f > s_f:
            span = e_f - s_f
            for ci in range(1, len(cards)):
                c_f = s_f + (ci * span) // len(cards)
                raw.append((max(s_f, c_f - 3), min(e_f, c_f + int(0.8 * fps))))
    raw.sort()
    merged: list[tuple[int, int]] = []
    for a, b in raw:
        if b <= a:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _adaptive_step_at(f: int, f_end: int, hi_ranges: list[tuple[int, int]], hi_step: int = 3, lo_step: int = 16) -> int:
    for a, b in hi_ranges:
        if a <= f < b:
            return max(1, min(hi_step, b - f, f_end - f))
        if a > f:
            return max(1, min(lo_step, a - f, f_end - f))
    return max(1, min(lo_step, f_end - f))


def render_shard(
    stage_html: Path,
    timeline_path: Path,
    out_mp4: Path,
    shard_idx: int,
    num_shards: int,
    crf: int = 21,
    preset: str = "veryfast",
    hi_step: int = 3,
    lo_step: int = 16,
) -> Path:
    from playwright.sync_api import sync_playwright

    tl = json.loads(timeline_path.read_text(encoding="utf-8"))
    fps = int(tl.get("fps", 24))
    total_frames = int(tl.get("total_frames") or round(float(tl.get("total_duration_sec", 7260.0)) * fps))
    hi_ranges = _compute_high_motion_windows(tl, fps)

    f_start = ((shard_idx - 1) * total_frames) // num_shards
    f_end = (shard_idx * total_frames) // num_shards
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = get_ffmpeg_exe()
    cmd = [
        ffmpeg, "-y", "-nostats", "-loglevel", "warning",
        "-f", "image2pipe", "-vcodec", "mjpeg", "-framerate", str(fps), "-i", "pipe:0",
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-g", str(fps * 2), "-bf", "2",
        "-r", str(fps), "-movflags", "+faststart", str(out_mp4),
    ]

    print(
        f"[LANG SHARD {shard_idx}/{num_shards}] Frames {f_start}..{f_end - 1} @ {fps}fps "
        f"smart({hi_step}/{lo_step}) preset={preset}",
        flush=True,
    )
    ff_log = out_mp4.with_suffix(".ffmpeg.log")
    rendered_unique = 0
    with open(ff_log, "wb") as err_fh:
        ff = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=err_fh)
        assert ff.stdin is not None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
                page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
                page.goto(stage_html.resolve().as_uri(), wait_until="load")
                page.evaluate("() => document.fonts ? document.fonts.ready : Promise.resolve()")

                f = f_start
                while f < f_end:
                    t_sec = f / fps
                    page.evaluate("([t, fi]) => window.renderAtTimeAsync(t, fi)", [t_sec, f])
                    jpg = page.screenshot(type="jpeg", quality=90, animations="disabled")
                    repeat = _adaptive_step_at(f, f_end, hi_ranges, hi_step=hi_step, lo_step=lo_step)
                    for _ in range(repeat):
                        ff.stdin.write(jpg)
                    rendered_unique += 1
                    f += repeat
                    if rendered_unique % 300 == 0:
                        pct = 100.0 * (f - f_start) / max(1, f_end - f_start)
                        print(f"[LANG SHARD {shard_idx}/{num_shards}] Progress {pct:.1f}% (captures={rendered_unique})", flush=True)
                browser.close()
            ff.stdin.close()
            rc = ff.wait()
            if rc != 0:
                err = ff_log.read_text(encoding="utf-8", errors="ignore")
                raise RuntimeError(f"FFmpeg shard {shard_idx} failed: {err[-500:]}")
        finally:
            if ff.poll() is None:
                ff.kill()
    ff_log.unlink(missing_ok=True)
    info = probe_media_info(out_mp4)
    print(f"LANG_SHARD_DONE {shard_idx}/{num_shards}: dur={info.get('duration', 0):.2f}s captures={rendered_unique}", flush=True)
    return out_mp4


def merge_shards_with_audio(
    shards_dir: Path,
    audio_m4a: Path,
    out_mp4: Path,
    num_shards: int = 8,
    min_expected_sec: float = 7200.0,
) -> dict[str, Any]:
    shard_files = [shards_dir / f"shard_{i:02d}_of_{num_shards:02d}.mp4" for i in range(1, num_shards + 1)]
    missing = [str(p) for p in shard_files if not (p.exists() and p.stat().st_size > 1000)]
    if missing:
        raise FileNotFoundError(f"Missing render shards: {missing}")

    concat_list = shards_dir / "concat_list.txt"
    concat_list.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in shard_files) + "\n", encoding="utf-8")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = get_ffmpeg_exe()
    subprocess.run(
        [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-i", str(audio_m4a), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0", "-map", "1:a:0", "-shortest", "-movflags", "+faststart", str(out_mp4),
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
    )
    info = probe_media_info(out_mp4)
    dur = float(info.get("duration", 0.0))
    if dur < min_expected_sec:
        raise RuntimeError(f"Merged duration {dur:.2f}s below floor {min_expected_sec}s!")
    res = {
        "out_mp4": str(out_mp4),
        "duration_sec": round(dur, 2),
        "duration_min": round(dur / 60.0, 2),
        "size_mb": round(out_mp4.stat().st_size / (1024 * 1024), 2),
        "width": info.get("width", 1920),
        "height": info.get("height", 1080),
    }
    print(f"LANG_MERGE_OK: {json.dumps(res, ensure_ascii=False)}", flush=True)
    return res


def main() -> None:
    parser = argparse.ArgumentParser(description="Playwright Smart-Step Shard Renderer & Merger for Language Studio")
    parser.add_argument("--stage-html", type=Path)
    parser.add_argument("--timeline", type=Path)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--merge", action="store_true")
    parser.add_argument("--shards-dir", type=Path)
    parser.add_argument("--audio", type=Path)
    parser.add_argument("--shard", type=int, default=1)
    parser.add_argument("--num-shards", type=int, default=8)
    parser.add_argument("--hi-step", type=int, default=3)
    parser.add_argument("--lo-step", type=int, default=16)
    parser.add_argument("--crf", type=int, default=21)
    parser.add_argument("--preset", default="veryfast")
    parser.add_argument("--min-sec", type=float, default=7200.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    if args.smoke:
        render_smoke_previews(args.stage_html, args.timeline, args.out)
    elif args.merge:
        merge_shards_with_audio(args.shards_dir, args.audio, args.out, num_shards=args.num_shards, min_expected_sec=args.min_sec)
    else:
        render_shard(
            args.stage_html, args.timeline, args.out,
            shard_idx=args.shard, num_shards=args.num_shards,
            crf=args.crf, preset=args.preset, hi_step=args.hi_step, lo_step=args.lo_step,
        )


if __name__ == "__main__":
    main()
