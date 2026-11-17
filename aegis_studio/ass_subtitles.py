"""Cinema-grade Advanced SubStation Alpha (.ass) & SRT Subtitle Builder (RTL-safe for libass)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import textwrap


@dataclass
class SubtitleSegment:
    """Single timed subtitle entry with optional translation and word timings."""

    index: int
    start: float
    end: float
    text: str
    translated_text: str = ""
    words: list[dict[str, float | str]] = field(default_factory=list)


STYLE_PRESETS = {
    "cinema": {
        "font": "Cairo",
        "size": 54,
        "primary": "&H00FFFFFF",
        "secondary": "&H0048D5FF",
        "outline_col": "&H00101014",
        "back_col": "&H78000000",
        "border_style": 1,
        "outline": 2.8,
        "shadow": 1.6,
        "margin_v": 58,
        "bold": -1,
    },
    "box": {
        "font": "Noto Sans Arabic",
        "size": 52,
        "primary": "&H00F8FAFC",
        "secondary": "&H0038BDF8",
        "outline_col": "&H96090D16",
        "back_col": "&H96090D16",
        "border_style": 3,
        "outline": 12.0,
        "shadow": 0.0,
        "margin_v": 56,
        "bold": -1,
    },
    "shorts": {
        "font": "Cairo",
        "size": 68,
        "primary": "&H00FFFFFF",
        "secondary": "&H0000D4FF",
        "outline_col": "&H00080C14",
        "back_col": "&H64000000",
        "border_style": 1,
        "outline": 4.2,
        "shadow": 2.2,
        "margin_v": 220,
        "bold": -1,
    },
    "educational": {
        "font": "Noto Sans Arabic",
        "size": 48,
        "primary": "&H00FEF3C7",
        "secondary": "&H0034D399",
        "outline_col": "&H000B1E3D",
        "back_col": "&H88050C1C",
        "border_style": 3,
        "outline": 10.0,
        "shadow": 0.0,
        "margin_v": 42,
        "bold": -1,
    },
}


def format_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp H:MM:SS.cc."""
    sec = max(0.0, float(seconds))
    cs_total = int(round(sec * 100))
    hrs, rem = divmod(cs_total, 360000)
    mins, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hrs}:{mins:02d}:{secs:02d}.{cs:02d}"


def format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp HH:MM:SS,mmm."""
    sec = max(0.0, float(seconds))
    ms_total = int(round(sec * 1000))
    hrs, rem = divmod(ms_total, 3600000)
    mins, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"


def wrap_balanced_lines(text: str, max_chars: int = 44) -> str:
    """Wrap subtitle text neatly into at most 2 visually balanced lines for ASS (\\N)."""
    clean = " ".join((text or "").split())
    if len(clean) <= max_chars:
        return clean
    lines = textwrap.wrap(clean, width=max_chars, break_long_words=False, break_on_hyphens=False)
    if len(lines) <= 2:
        return "\\N".join(lines)
    # Rebalance into 2 halves so bottom-screen occlusion stays minimal
    mid = len(clean) // 2
    split_pos = clean.rfind(" ", 0, mid + 8)
    if split_pos <= 0:
        split_pos = clean.find(" ", mid)
    if split_pos > 0:
        return f"{clean[:split_pos].strip()}\\N{clean[split_pos + 1:].strip()}"
    return "\\N".join(lines[:2])


def _karaoke_line(words: list[dict[str, float | str]]) -> str:
    """Generate ASS \\kf karaoke tags when word timings are present."""
    chunks: list[str] = []
    for w in words:
        token = str(w.get("word") or "").strip()
        if not token:
            continue
        dur_cs = max(8, int(round((float(w.get("end", 0)) - float(w.get("start", 0))) * 100)))
        chunks.append(f"{{\\kf{dur_cs}}}{token} ")
    return "".join(chunks).strip()


def write_ass_file(
    segments: list[SubtitleSegment],
    out_ass: Path,
    video_width: int = 1920,
    video_height: int = 1080,
    preset: str = "cinema",
    dual_language: bool = False,
    karaoke: bool = False,
) -> Path:
    """Render styled ASS file suitable for libass + HarfBuzz RTL shaping."""
    cfg = STYLE_PRESETS.get(preset, STYLE_PRESETS["cinema"])
    scale = max(0.55, min(2.0, video_height / 1080.0))
    font_size = max(24, int(round(cfg["size"] * scale)))
    sec_size = max(18, int(round(font_size * 0.68)))
    margin_v = int(round(cfg["margin_v"] * scale))
    outline = round(cfg["outline"] * scale, 2)
    shadow = round(cfg["shadow"] * scale, 2)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{cfg['font']},{font_size},{cfg['primary']},{cfg['secondary']},{cfg['outline_col']},{cfg['back_col']},{cfg['bold']},0,0,0,100,100,0,0,{cfg['border_style']},{outline},{shadow},2,48,48,{margin_v},1
Style: Original,DejaVu Sans,{sec_size},&H00CBD5E1,&H0094A3B8,&H000F172A,&H70000000,0,0,0,0,100,100,0,0,1,{max(1.5, outline * 0.7):.2f},1.0,2,48,48,{margin_v + int(font_size * 2.15)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    for seg in segments:
        st = format_ass_time(seg.start)
        en = format_ass_time(max(seg.end, seg.start + 0.35))
        primary_txt = seg.translated_text.strip() or seg.text.strip()
        if not primary_txt:
            continue
        if karaoke and seg.words and not seg.translated_text.strip():
            main_body = _karaoke_line(seg.words) or wrap_balanced_lines(primary_txt)
        else:
            main_body = wrap_balanced_lines(primary_txt, max_chars=34 if video_width < video_height else 46)
        events.append(f"Dialogue: 1,{st},{en},Main,,0,0,0,,{{\\fad(80,60)}}{main_body}")

        if dual_language and seg.translated_text.strip() and seg.text.strip():
            orig_body = wrap_balanced_lines(seg.text.strip(), max_chars=52)
            events.append(f"Dialogue: 0,{st},{en},Original,,0,0,0,,{{\\fad(80,60)}}{orig_body}")

    out_ass.parent.mkdir(parents=True, exist_ok=True)
    out_ass.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return out_ass


def write_srt_file(segments: list[SubtitleSegment], out_srt: Path, use_translated: bool = True) -> Path:
    """Export standard UTF-8 SRT sidecar."""
    blocks: list[str] = []
    idx = 1
    for seg in segments:
        body = (seg.translated_text if use_translated and seg.translated_text.strip() else seg.text).strip()
        if not body:
            continue
        blocks.append(f"{idx}\n{format_srt_time(seg.start)} --> {format_srt_time(seg.end)}\n{body}\n")
        idx += 1
    out_srt.parent.mkdir(parents=True, exist_ok=True)
    out_srt.write_text("\n".join(blocks), encoding="utf-8")
    return out_srt
