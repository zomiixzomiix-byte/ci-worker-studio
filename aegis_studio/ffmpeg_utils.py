"""Shared FFmpeg / NVENC / Audio Normalization & Subtitle Escaping Helpers."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import wave
from pathlib import Path

_NVENC_CACHE: bool | None = None


def get_ffmpeg_exe() -> str:
    """Resolve FFmpeg binary from system PATH or imageio_ffmpeg bundle."""
    env_bin = os.environ.get("FFMPEG_BIN")
    if env_bin and Path(env_bin).exists():
        return env_bin
    sys_bin = shutil.which("ffmpeg")
    if sys_bin:
        return sys_bin
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def has_nvenc_gpu(ffmpeg_bin: str | None = None) -> bool:
    """Probe whether NVIDIA h264_nvenc works in this cloud/local environment."""
    global _NVENC_CACHE
    if _NVENC_CACHE is not None:
        return _NVENC_CACHE
    exe = ffmpeg_bin or get_ffmpeg_exe()
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-f", "lavfi", "-i", "color=c=black:s=128x128:d=0.2", "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        _NVENC_CACHE = proc.returncode == 0
    except Exception:
        _NVENC_CACHE = False
    return _NVENC_CACHE


def best_h264_video_flags(preset_quality: str = "cinema", force_cpu: bool = False) -> list[str]:
    """Return optimal NVENC GPU flags when available, otherwise crisp CPU libx264 flags."""
    if not force_cpu and has_nvenc_gpu():
        cq = "18" if preset_quality == "cinema" else "21"
        return ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr", "-cq", cq, "-b:v", "0", "-pix_fmt", "yuv420p"]
    if preset_quality == "cinema":
        return ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]


def escape_ffmpeg_filter_path(path: Path | str) -> str:
    """Escape path safely for FFmpeg filter arguments on both Linux and Windows."""
    clean = str(Path(path).resolve()).replace("\\", "/")
    if len(clean) >= 2 and clean[1] == ":":
        clean = clean[0] + "\\:" + clean[2:]
    return clean.replace("'", "\\'")


def probe_media_info(media_path: Path | str) -> dict[str, float | int]:
    """Probe duration (seconds), width, height via ffmpeg stderr output."""
    exe = get_ffmpeg_exe()
    proc = subprocess.run([exe, "-hide_banner", "-i", str(media_path)], capture_output=True, text=True, errors="replace")
    dur = 0.0
    m_dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if m_dur:
        h, mn, s = m_dur.groups()
        dur = int(h) * 3600 + int(mn) * 60 + float(s)
    w, h_px = 1920, 1080
    m_res = re.search(r"Video:.*?\b(\d{3,4})x(\d{3,4})\b", proc.stderr)
    if m_res:
        w, h_px = int(m_res.group(1)), int(m_res.group(2))
    return {"duration": dur, "width": w, "height": h_px}


def save_tts_audio_normalized(audio_bytes: bytes, out_audio_path: Path, sample_rate: int = 24000) -> Path:
    """Convert raw Gemini PCM/RIFF audio bytes into broadcast-loudness-normalized MP3/M4A."""
    out_audio_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_wav = out_audio_path.with_suffix(".tmp_tts.wav")
    if audio_bytes[:4] == b"RIFF":
        tmp_wav.write_bytes(audio_bytes)
    else:
        with wave.open(str(tmp_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_bytes)

    exe = get_ffmpeg_exe()
    ext = out_audio_path.suffix.lower()
    codec_flags = ["-c:a", "aac", "-b:a", "192k"] if ext in (".m4a", ".aac") else ["-c:a", "libmp3lame", "-b:a", "192k"]
    subprocess.run(
        [
            exe, "-y", "-i", str(tmp_wav),
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", "48000", "-ac", "2",
            *codec_flags,
            str(out_audio_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    tmp_wav.unlink(missing_ok=True)
    return out_audio_path


def extract_clean_wav16k(video_path: Path, out_wav: Path) -> Path:
    """Extract 16kHz mono WAV optimal for speech analysis and Whisper."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [get_ffmpeg_exe(), "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out_wav)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    return out_wav


def download_source_video(source: str, work_dir: Path) -> Path:
    """Resolve local file, pull streaming URL via yt-dlp (YouTube/social), or fetch direct HTTP MP4."""
    if not source.startswith(("http://", "https://")):
        p = Path(source)
        if not p.exists():
            raise FileNotFoundError(f"Source video not found: {source}")
        return p

    work_dir.mkdir(parents=True, exist_ok=True)
    ytdlp_bin = shutil.which("yt-dlp")
    is_direct_media = any(source.lower().split("?")[0].endswith(ext) for ext in (".mp4", ".mkv", ".mov", ".webm", ".mp3", ".wav"))
    out_mp4 = work_dir / "pulled_source.mp4"

    if ytdlp_bin and not is_direct_media:
        cmd = [
            ytdlp_bin,
            "--no-playlist",
            "-f", "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best",
            "--merge-output-format", "mp4",
            "-o", str(work_dir / "pulled_source.%(ext)s"),
            source,
        ]
        subprocess.run(cmd, check=True)
        for cand in sorted(work_dir.glob("pulled_source.*")):
            if cand.is_file() and cand.stat().st_size > 1024:
                return cand

    import urllib.request

    urllib.request.urlretrieve(source, out_mp4)
    return out_mp4


def build_transition_whoosh(out_wav: Path, duration_sec: float = 0.42) -> Path:
    """Synthesize a clean, royalty-free soft air whoosh sound effect via FFmpeg filtergraph."""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    exe = get_ffmpeg_exe()
    af = (
        f"bandpass=f=720:width_type=h:w=520,"
        f"afade=t=in:st=0:d=0.14,"
        f"afade=t=out:st={max(0.08, duration_sec - 0.24):.2f}:d=0.22,"
        f"volume=0.22"
    )
    subprocess.run(
        [
            exe, "-y",
            "-f", "lavfi", "-i", f"anoisesrc=c=pink:r=48000:a=0.35:d={duration_sec:.2f}",
            "-af", af, "-ar", "48000", "-ac", "2",
            str(out_wav),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    return out_wav


def mix_audio_with_subtle_bed_and_sfx(
    narration_wavs: list[tuple[float, Path]],
    total_duration: float,
    out_mp3: Path,
    enable_sfx: bool = True,
) -> Path:
    """Concatenate/place scene narrations, mix subtle scene-transition whoosh + warm low harmonic bed."""
    exe = get_ffmpeg_exe()
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = out_mp3.parent / "_audio_mix_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # First place each scene clip at its start timestamp in sequential chunks (safe cmd length)
    placed_wavs: list[Path] = []
    for idx, (start_s, clip_p) in enumerate(narration_wavs):
        placed_wavs.append(clip_p)

    # Concatenate voice tracks cleanly (padded to each scene boundary or direct ordered concat with 0.25s silence gap)
    concat_txt = tmp_dir / "voice_concat.txt"
    sil_wav = tmp_dir / "gap_250ms.wav"
    subprocess.run(
        [exe, "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=0.25", "-ar", "48000", "-ac", "2", str(sil_wav)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    norm_clips: list[Path] = []
    for i, (_st, src_audio) in enumerate(narration_wavs):
        w_out = tmp_dir / f"v_{i:03d}.wav"
        subprocess.run(
            [exe, "-y", "-i", str(src_audio), "-ar", "48000", "-ac", "2", str(w_out)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        norm_clips.append(w_out)

    lines: list[str] = []
    for i, wc in enumerate(norm_clips):
        lines.append(f"file '{wc.resolve().as_posix()}'")
        if i < len(norm_clips) - 1:
            lines.append(f"file '{sil_wav.resolve().as_posix()}'")
    concat_txt.write_text("\n".join(lines), encoding="utf-8")

    voice_master = tmp_dir / "voice_master.wav"
    subprocess.run(
        [exe, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_txt), "-ar", "48000", "-ac", "2", str(voice_master)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )

    if not enable_sfx:
        subprocess.run(
            [exe, "-y", "-i", str(voice_master), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "libmp3lame", "-b:a", "192k", str(out_mp3)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return out_mp3

    # Synthesize subtle warm harmonic background drone (-25dB under voice, zero copyright issues)
    dur_safe = max(2.0, float(total_duration or probe_media_info(voice_master)["duration"] or 3.0))
    bed_expr = "0.28*sin(2*PI*110*t)+0.22*sin(2*PI*164.81*t)+0.16*sin(2*PI*220*t)+0.12*sin(2*PI*277.18*t)"
    cmd = [
        exe, "-y",
        "-i", str(voice_master),
        "-f", "lavfi", "-i", f"aevalsrc={bed_expr}:s=48000:c=stereo:d={dur_safe:.2f}",
    ]
    filter_parts = [
        "[1:a]lowpass=f=420,afade=t=in:st=0:d=1.0,afade=t=out:st=" + f"{max(0.5, dur_safe - 1.2):.2f}" + ":d=1.0,volume=0.055[bed]",
        "[0:a]asplit=2[v][sc]",
        "[bed][sc]sidechaincompress=threshold=0.02:ratio=4:attack=90:release=400[ducked]",
    ]
    mix_inputs = ["[ducked]", "[v]"]

    # Optional scene transition whooshes when multiple scenes exist
    transition_starts = [round(st, 2) for st, _ in narration_wavs[1:] if st > 0.3][:20]
    if transition_starts:
        whoosh = build_transition_whoosh(tmp_dir / "whoosh.wav")
        cmd.extend(["-i", str(whoosh)])
        w_idx = 2
        if len(transition_starts) == 1:
            d_ms = int(transition_starts[0] * 1000)
            filter_parts.append(f"[{w_idx}:a]adelay={d_ms}|{d_ms},volume=0.55[sfx_all]")
        else:
            filter_parts.append(f"[{w_idx}:a]asplit={len(transition_starts)}" + "".join(f"[w{j}]" for j in range(len(transition_starts))))
            sfx_tags: list[str] = []
            for j, ts in enumerate(transition_starts):
                d_ms = int(ts * 1000)
                filter_parts.append(f"[w{j}]adelay={d_ms}|{d_ms},volume=0.55[wd{j}]")
                sfx_tags.append(f"[wd{j}]")
            filter_parts.append(f"{''.join(sfx_tags)}amix=inputs={len(sfx_tags)}:normalize=0[sfx_all]")
        mix_inputs.append("[sfx_all]")

    filter_parts.append(
        f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[final]"
    )
    cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", "[final]", "-t", f"{dur_safe:.2f}", "-c:a", "libmp3lame", "-b:a", "192k", str(out_mp3)])
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return out_mp3

