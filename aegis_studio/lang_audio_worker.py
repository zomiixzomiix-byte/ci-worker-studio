"""Language Master Studio — 2+ Hour Bilingual Audio & Rapid-Fluency Podcast Pipeline.

Synthesizes bilingual German/Arabic teacher narration via AegisStudioClient (Gemini TTS),
decodes & RMS-normalizes authentic Hueber Kursbuch/Arbeitsbuch MP3 tracks, renders timing
chimes, mixes speech-only ambient bed (muted during Hueber originals), computes per-frame
RMS audio reactivity, writes synced ASS/SRT/timeline metadata, and assembles a dedicated
~35-45 min Rapid-Fluency Active-Recall & Shadowing Podcast MP3 at ZERO extra TTS cost.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import io
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import wave
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Fallback sibling lookup when executed inside aegis_cloud_video_studio alongside ci-worker-7c4e
_PUBLIC_WORKER_ROOT = ROOT.parent / "aegis_cloud_render_public"
if _PUBLIC_WORKER_ROOT.exists() and str(_PUBLIC_WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(_PUBLIC_WORKER_ROOT))

from aegis_studio.aegis_client import AegisStudioClient
from aegis_studio.ass_subtitles import SubtitleSegment, write_ass_file, write_srt_file
from aegis_studio.ffmpeg_utils import get_ffmpeg_exe, save_tts_audio_normalized

SAMPLE_RATE = 24000
TARGET_MIN_SEC = 7260.0  # > 2h01m safety floor

SPEAKER_VOICE_MAP = {
    "lehrerin": "Aoede",
    "lehrer": "Charon",
}


def _decode_audio_to_f32(audio_path: Path, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Decode any audio file to trimmed mono float32 PCM at `sr` Hz via FFmpeg."""
    ffmpeg = get_ffmpeg_exe()
    cmd = [
        ffmpeg, "-y", "-i", str(audio_path),
        "-ac", "1", "-ar", str(sr),
        "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1",
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True)
    arr = np.frombuffer(res.stdout, dtype=np.float32)
    return _trim_edge_silence(arr, sr=sr)


def _trim_edge_silence(arr: np.ndarray, sr: int = SAMPLE_RATE, thresh_db: float = -46.0) -> np.ndarray:
    if arr.size == 0:
        return arr
    thresh = 10.0 ** (thresh_db / 20.0)
    win = max(1, int(0.015 * sr))
    abs_arr = np.abs(arr)
    idx_active = np.where(abs_arr > thresh)[0]
    if idx_active.size == 0:
        return arr
    start = max(0, int(idx_active[0]) - win * 2)
    end = min(arr.size, int(idx_active[-1]) + win * 3)
    trimmed = arr[start:end].copy()
    fade = min(int(0.008 * sr), trimmed.size // 4)
    if fade > 0:
        trimmed[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
        trimmed[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
    return trimmed


def _cap_and_fade(arr: np.ndarray, max_sec: float, sr: int = SAMPLE_RATE, fade_sec: float = 2.5) -> np.ndarray:
    """Smoothly cap long Hueber tracks (e.g., songs) with a clean fade-out so playback never stalls visuals."""
    max_samples = max(sr, int(max_sec * sr))
    if arr.size <= max_samples:
        return arr
    out = arr[:max_samples].copy()
    fade_len = min(int(fade_sec * sr), out.size // 2)
    if fade_len > 0:
        ramp = 0.5 * (1.0 + np.cos(np.linspace(0.0, math.pi, fade_len, dtype=np.float32)))
        out[-fade_len:] *= ramp
    return out


def _normalize_rms(arr: np.ndarray, target_rms: float = 0.145) -> np.ndarray:
    if arr.size == 0:
        return arr
    rms = float(np.sqrt(np.mean(arr ** 2)))
    if rms < 1e-5:
        return arr
    gain = min(4.2, target_rms / rms)
    return np.clip(arr * gain, -0.92, 0.92).astype(np.float32)


def _synthesize_soft_bell(freq: float, dur: float, amp: float = 0.13, sr: int = SAMPLE_RATE) -> np.ndarray:
    t = np.arange(int(dur * sr), dtype=np.float32) / sr
    env = np.exp(-3.4 * t) * (1.0 - np.exp(-42.0 * t))
    tone = 0.7 * np.sin(2.0 * np.pi * freq * t) + 0.3 * np.sin(2.0 * np.pi * freq * 2.0 * t)
    return (tone * env * amp).astype(np.float32)


def _build_countdown_audio(dur_sec: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    n = max(int(dur_sec * sr), sr)
    buf = np.zeros(n, dtype=np.float32)
    for step, sec in enumerate(np.arange(0.35, max(0.5, dur_sec - 0.15), 1.0)):
        freq = 587.33 if step < int(dur_sec) - 1 else 880.0
        ding = _synthesize_soft_bell(freq, 0.42, amp=0.13, sr=sr)
        idx = int(sec * sr)
        end = min(buf.size, idx + ding.size)
        buf[idx:end] += ding[: end - idx]
    return buf


def _build_academic_ambient(total_samples: int, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Gentle minimalist harmonic pad (D add9 calm study timbre), tiled cleanly for low RAM."""
    loop_sec = 24
    loop_n = loop_sec * sr
    t = np.arange(loop_n, dtype=np.float32) / sr
    chord = (
        0.35 * np.sin(2.0 * np.pi * 146.83 * t)
        + 0.25 * np.sin(2.0 * np.pi * 220.00 * t)
        + 0.22 * np.sin(2.0 * np.pi * 277.18 * t)
        + 0.14 * np.sin(2.0 * np.pi * 329.63 * t)
    )
    lfo = 0.65 + 0.35 * np.sin(2.0 * np.pi * (1.0 / loop_sec) * t)
    block = (chord * lfo * 0.020).astype(np.float32)
    return np.resize(block, total_samples)


def _boxcar_smooth(arr: np.ndarray, win: int) -> np.ndarray:
    """O(N) prefix-sum moving average smoothing (avoids multi-minute O(N*W) np.convolve)."""
    if win <= 1 or arr.size <= 2:
        return arr
    pad_l = win // 2
    pad_r = win - 1 - pad_l
    padded = np.pad(arr.astype(np.float64), (pad_l, pad_r), mode="edge")
    csum = np.empty(padded.size + 1, dtype=np.float64)
    csum[0] = 0.0
    np.cumsum(padded, out=csum[1:])
    return ((csum[win:] - csum[:-win]) / float(win)).astype(np.float32)


def _split_bilingual_sentences(text: str) -> list[str]:
    clean = " ".join((text or "").split())
    if not clean:
        return []
    parts = re.split(r"(?<=[.!?؟!])\s+", clean)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > 135 and (":" in p or "—" in p or "،" in p or "," in p):
            sub_chunks = re.split(r"(?<=[—:,،;])\s+", p)
            acc = ""
            for sc in sub_chunks:
                if len(acc) + len(sc) + 1 <= 118:
                    acc = f"{acc} {sc}".strip()
                else:
                    if acc:
                        out.append(acc)
                    acc = sc
            if acc:
                out.append(acc)
        else:
            out.append(p)
    return out


_EDGE_SEM = threading.Semaphore(8)
_PIPER_LOCK = threading.Lock()
_PIPER_VOICES: dict[str, Any] = {}


def _split_lang_segments(txt: str) -> list[tuple[str, str]]:
    """Coalesce mixed Arabic+German narration into minimal clean ('ar'|'de', text) runs."""
    raw = re.findall(
        r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF0-9\s،؛؟.,!:\-\(\)«»/]+|"
        r"[A-Za-zÄÖÜäöüß]+(?:[\s.,!?;:\-/'\"0-9]+[A-Za-zÄÖÜäöüß0-9]+)*",
        txt or "",
    )
    merged: list[tuple[str, str]] = []
    for piece in raw:
        c = piece.strip()
        if not c:
            continue
        if re.search(r"[\u0600-\u06FF]", c):
            lang = "ar"
        elif re.search(r"[A-Za-zÄÖÜäöüß]", c):
            lang = "de"
        else:
            continue
        if merged and merged[-1][0] == lang:
            merged[-1] = (lang, f"{merged[-1][1]} {c}")
        else:
            merged.append((lang, c))
    return merged


def _ensure_piper_voice(lang: str, piper_dir: Path | None) -> Any:
    """Lazy-load offline CPU neural ONNX voice (100% rate-limit proof Tier 3)."""
    from piper.voice import PiperVoice

    with _PIPER_LOCK:
        if lang in _PIPER_VOICES:
            return _PIPER_VOICES[lang]
        cache_d = piper_dir or (Path.home() / ".cache" / "piper_voices")
        cache_d.mkdir(parents=True, exist_ok=True)
        specs = {
            "de": ("de_DE-thorsten-low.onnx", "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/low/de_DE-thorsten-low.onnx"),
            "ar": ("ar_JO-kareem-low.onnx", "https://huggingface.co/rhasspy/piper-voices/resolve/main/ar/ar_JO/kareem/low/ar_JO-kareem-low.onnx"),
        }
        fname, url = specs[lang]
        onnx_p = cache_d / fname
        json_p = cache_d / f"{fname}.json"
        if not onnx_p.exists():
            urllib.request.urlretrieve(url, str(onnx_p))
        if not json_p.exists():
            urllib.request.urlretrieve(f"{url}.json", str(json_p))
        v = PiperVoice.load(str(onnx_p))
        _PIPER_VOICES[lang] = v
        return v


def _edge_synth_segments(segs: list[tuple[str, str]], edge_map: dict[str, str]) -> list[bytes]:
    import edge_tts

    async def _go() -> list[bytes]:
        sem = asyncio.Semaphore(4)

        async def _one(clean: str, voice: str) -> bytes:
            async with sem:
                for att in range(2):
                    try:
                        comm = edge_tts.Communicate(clean, voice)
                        buf = bytearray()
                        async for msg in comm.stream():
                            if msg.get("type") == "audio":
                                buf.extend(msg["data"])
                        if len(buf) >= 512:
                            return bytes(buf)
                    except Exception:
                        if att == 0:
                            await asyncio.sleep(0.25)
                return b""

        return list(await asyncio.gather(*(_one(clean, edge_map[lang]) for lang, clean in segs)))

    return asyncio.run(_go())


def _synthesize_bilingual_neural(
    txt: str,
    voice_name: str,
    dst: Path,
    piper_dir: Path | None = None,
    sr: int = SAMPLE_RATE,
) -> tuple[Path, str]:
    """Tier 2 Edge Neural (AR+DE parallel multi-voice) with Tier 3 offline Piper ONNX safety net."""
    segs = _split_lang_segments(txt)
    if not segs:
        segs = [("de", (txt or "Lektion")[:200])]

    is_male = str(voice_name).lower() in ("charon", "lehrer", "fenrir", "puck")
    edge_map = {
        "ar": "ar-SA-HamedNeural" if is_male else "ar-SA-ZariyahNeural",
        "de": "de-DE-ConradNeural" if is_male else "de-DE-KatjaNeural",
    }

    arrays: list[np.ndarray] = []
    gap = np.zeros(int(0.08 * sr), dtype=np.float32)
    ffmpeg = get_ffmpeg_exe()
    used_piper = False

    with _EDGE_SEM:
        try:
            edge_chunks = _edge_synth_segments(segs, edge_map)
        except Exception:
            edge_chunks = [b""] * len(segs)

    for (lang, clean), audio_bytes in zip(segs, edge_chunks):
        fmt = "mp3"
        # Tier 3: 100% offline local CPU ONNX Piper fallback (impossible to rate-limit)
        if len(audio_bytes) < 512:
            used_piper = True
            pv = _ensure_piper_voice(lang, piper_dir)
            wbuf = io.BytesIO()
            with _PIPER_LOCK:
                with wave.open(wbuf, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(int(getattr(getattr(pv, "config", None), "sample_rate", 16000)))
                    pv.synthesize_wav(clean, wf, set_wav_format=False)
            audio_bytes = wbuf.getvalue()
            fmt = "wav"
            if len(audio_bytes) <= 64:
                continue

        res = subprocess.run(
            [ffmpeg, "-y", "-f", fmt, "-i", "pipe:0", "-ac", "1", "-ar", str(sr), "-f", "f32le", "pipe:1"],
            input=audio_bytes, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True,
        )
        pcm = _trim_edge_silence(np.frombuffer(res.stdout, dtype=np.float32), sr=sr)
        if pcm.size > 0:
            arrays.append(pcm)
            arrays.append(gap)

    combined = _normalize_rms(np.concatenate(arrays)) if arrays else np.zeros(int(1.2 * sr), dtype=np.float32)
    tmp_raw = dst.with_suffix(".f32")
    dst.parent.mkdir(parents=True, exist_ok=True)
    combined.tofile(str(tmp_raw))
    try:
        subprocess.run(
            [ffmpeg, "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", str(tmp_raw), "-c:a", "libmp3lame", "-b:a", "128k", str(dst)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
        )
    finally:
        tmp_raw.unlink(missing_ok=True)
    return dst, ("piper_offline_onnx" if used_piper else "edge_neural_ar_de")


def _synthesize_batch(
    client: AegisStudioClient,
    jobs: list[tuple[str, str, str, Path]],
    max_workers: int = 4,
    piper_dir: Path | None = None,
) -> dict[str, Path]:
    results: dict[str, Path] = {}
    pending = []
    for eid, txt, voice, dst in jobs:
        if dst.exists() and dst.stat().st_size > 1200:
            results[eid] = dst
        else:
            pending.append((eid, txt, voice, dst))

    if not pending:
        print(f"[LANG AUDIO] All {len(jobs)} bilingual TTS clips already cached.", flush=True)
        return results

    print(
        f"[LANG AUDIO] Synthesizing {len(pending)}/{len(jobs)} bilingual clips "
        f"(workers={max_workers})...",
        flush=True,
    )

    def _run_one(idx_item: tuple[int, tuple[str, str, str, Path]]) -> tuple[str, Path, str]:
        idx, (eid, txt, voice, dst) = idx_item
        if idx < max_workers:
            time.sleep(0.25 * idx)
        clean_txt = re.sub(r"[`*_#]+", "", (txt or "").strip())
        spoken = (
            "[speaking warmly like an expert Goethe-Institut bilingual German-Arabic professor, "
            "pronouncing German phrases crisply and explaining fluently in Modern Standard Arabic] "
            f"{clean_txt}"
        )
        last_exc: Exception | None = None
        for att in range(3):
            prompt = spoken if att == 0 else clean_txt
            try:
                raw_bytes, _mime, model_used = client.synthesize_tts(prompt, voice_name=voice, timeout_sec=36)
                save_tts_audio_normalized(raw_bytes, dst, sample_rate=SAMPLE_RATE)
                return eid, dst, model_used
            except Exception as exc:
                last_exc = exc
                time.sleep(2.0 * (att + 1) + random.uniform(0.2, 1.0))
        print(
            f"[LANG AUDIO] ⚠️ gemini-3.8-flash-tts failed for {eid} ({last_exc}); "
            "falling back to Edge/Piper neural TTS...",
            flush=True,
        )
        out_path, mod_fb = _synthesize_bilingual_neural(clean_txt, voice, dst, piper_dir=piper_dir)
        return eid, out_path, mod_fb

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_run_one, (i, it)): it[0] for i, it in enumerate(pending)}
        done_n = 0
        gem_n = 0
        edge_n = 0
        piper_n = 0
        for fut in concurrent.futures.as_completed(futs):
            re_id, path_out, mod = fut.result()
            results[re_id] = path_out
            done_n += 1
            if mod == "piper_offline_onnx":
                piper_n += 1
            elif mod == "edge_neural_ar_de":
                edge_n += 1
            else:
                gem_n += 1
            if done_n % 10 == 0 or done_n == len(pending):
                print(
                    f"[LANG AUDIO] Progress {done_n}/{len(pending)} "
                    f"(gemini={gem_n}, edge={edge_n}, piper={piper_n}, last={mod})",
                    flush=True,
                )
    return results


def _build_rapid_fluency_podcast(
    chapters: list[dict[str, Any]],
    decoded_clips: dict[str, np.ndarray],
    out_mp3_path: Path,
    sr: int = SAMPLE_RATE,
) -> dict[str, Any]:
    """Assemble ~35-45m Active-Recall & Shadowing Podcast MP3 from tagged lesson events (0 extra TTS calls)."""
    segments: list[np.ndarray] = []
    cue_chime = _synthesize_soft_bell(880.0, 0.22, amp=0.10, sr=sr)
    chapter_chime = _synthesize_soft_bell(587.33, 0.65, amp=0.12, sr=sr)

    intro_clip = decoded_clips.get("c1_01")
    if intro_clip is not None and intro_clip.size > 0:
        segments.append(chapter_chime)
        segments.append(np.zeros(int(0.4 * sr), dtype=np.float32))
        segments.append(intro_clip)
        segments.append(np.zeros(int(1.0 * sr), dtype=np.float32))

    item_count = 0
    for ch in chapters:
        for ev in ch.get("events", []):
            if not ev.get("in_podcast"):
                continue
            eid = ev["event_id"]
            clip = decoded_clips.get(eid)
            if clip is None or clip.size == 0:
                continue
            item_count += 1
            if ev.get("type") == "audio_track":
                segments.append(chapter_chime)
                segments.append(np.zeros(int(0.35 * sr), dtype=np.float32))
            segments.append(clip)

            mode = str(ev.get("podcast_mode") or "")
            if mode in ("vocab_recall", "dialogue") or ev.get("type") == "audio_track":
                # 2.4s active-recall / shadowing slot with subtle acoustic prompt cue
                gap = np.zeros(int(2.4 * sr), dtype=np.float32)
                end_c = min(gap.size, cue_chime.size)
                gap[:end_c] += cue_chime[:end_c]
                segments.append(gap)
            else:
                segments.append(np.zeros(int(0.55 * sr), dtype=np.float32))

    if not segments:
        segments.append(np.zeros(int(2.0 * sr), dtype=np.float32))

    segments.append(chapter_chime)
    segments.append(np.zeros(int(1.5 * sr), dtype=np.float32))

    podcast_arr = np.clip(np.concatenate(segments), -0.95, 0.95).astype(np.float32)
    pod_sec = podcast_arr.size / sr

    tmp_pod = out_mp3_path.with_suffix(".f32")
    podcast_arr.tofile(str(tmp_pod))
    ffmpeg = get_ffmpeg_exe()
    try:
        subprocess.run(
            [
                ffmpeg, "-y",
                "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", str(tmp_pod),
                "-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "160k",
                str(out_mp3_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    finally:
        tmp_pod.unlink(missing_ok=True)
    return {
        "podcast_mp3": str(out_mp3_path),
        "podcast_items": item_count,
        "podcast_duration_sec": round(pod_sec, 2),
        "podcast_duration_min": round(pod_sec / 60.0, 2),
    }


def build_menschen_audio_and_timeline(
    curriculum_path: Path,
    assets_dir: Path | None,
    out_dir: Path,
    client: AegisStudioClient | None = None,
    fps: int = 24,
    max_tts_workers: int = 6,
    min_duration_sec: float = TARGET_MIN_SEC,
    skip_tts_synthesis: bool = False,
    skip_full_mp3: bool = False,
    piper_dir: Path | None = None,
) -> dict[str, Any]:
    """Build master 2H+ AAC/MP3 audio, Rapid-Fluency Podcast MP3, synced timeline JSON, RMS array, and ASS/SRT."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tts_dir = out_dir / "tts_cache"
    tts_dir.mkdir(parents=True, exist_ok=True)

    cur = json.loads(curriculum_path.read_text(encoding="utf-8"))
    chapters = cur.get("chapters", [])
    lesson_id = str(cur.get("lesson_id") or "UNIT_LESSON")

    tts_jobs: list[tuple[str, str, str, Path]] = []
    for ch in chapters:
        for ev in ch.get("events", []):
            if ev.get("type", "teacher") == "teacher":
                eid = ev["event_id"]
                voice = str(ev.get("voice_name") or SPEAKER_VOICE_MAP.get(str(ev.get("speaker", "lehrerin")), "Aoede"))
                nar = str(ev.get("narration_fr") or (ev.get("board_data") or {}).get("heading") or "Wir machen weiter.").strip()
                tts_jobs.append((eid, nar, voice, tts_dir / f"{eid}.mp3"))

    if tts_jobs and not skip_tts_synthesis:
        aegis = client or AegisStudioClient()
        tts_map = _synthesize_batch(aegis, tts_jobs, max_workers=max_tts_workers, piper_dir=piper_dir)
    else:
        tts_map = {eid: dst for eid, _nar, _v, dst in tts_jobs if dst.exists()}

    decoded_clips: dict[str, np.ndarray] = {}
    raw_speech_sec = 0.0
    non_speech_sec = 0.0
    flat_items: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for ch in chapters:
        for ev in ch.get("events", []):
            eid = ev["event_id"]
            etype = ev.get("type", "teacher")
            if etype == "teacher":
                p = tts_map.get(eid)
                if p and p.exists():
                    arr = _normalize_rms(_decode_audio_to_f32(p, SAMPLE_RATE))
                else:
                    # Fast concise dry-run placeholder (~1.2s) for offline pipeline verification
                    arr = np.zeros(int(1.2 * SAMPLE_RATE), dtype=np.float32)
                decoded_clips[eid] = arr
                raw_speech_sec += arr.size / SAMPLE_RATE
            elif etype == "audio_track":
                rel = str(ev.get("audio_rel_path") or "")
                max_s = float(ev.get("max_sec", 70.0))
                aud_file = (assets_dir / rel) if (assets_dir and rel) else None
                if aud_file and aud_file.exists():
                    arr = _decode_audio_to_f32(aud_file, SAMPLE_RATE)
                    arr = _cap_and_fade(arr, max_sec=max_s, sr=SAMPLE_RATE, fade_sec=2.5)
                    arr = _normalize_rms(arr, target_rms=0.15)
                else:
                    arr = _synthesize_soft_bell(392.0, 4.0, amp=0.06, sr=SAMPLE_RATE)
                decoded_clips[eid] = arr
                non_speech_sec += arr.size / SAMPLE_RATE
            elif etype == "countdown":
                dur = float(ev.get("dur_sec", 4.0))
                decoded_clips[eid] = _build_countdown_audio(dur, sr=SAMPLE_RATE)
                non_speech_sec += dur
            flat_items.append((ch, ev))

    inter_pause = 0.70
    chapter_pause = 2.0
    base_pause_sec = len(flat_items) * inter_pause + len(chapters) * chapter_pause
    raw_total = raw_speech_sec + non_speech_sec + base_pause_sec

    extra_inter_pause = 0.0
    if raw_total < min_duration_sec and flat_items:
        deficit = min_duration_sec - raw_total
        extra_inter_pause = min(1.85, deficit / len(flat_items))
        deficit -= extra_inter_pause * len(flat_items)
        if deficit > 0:
            chapter_pause += deficit / max(1, len(chapters))

    master_segments: list[np.ndarray] = []
    sfx_events: list[tuple[float, np.ndarray]] = []
    speech_mask_ranges: list[tuple[float, float]] = []
    mute_pad_ranges: list[tuple[float, float]] = []
    timeline_events: list[dict[str, Any]] = []
    chapter_markers: list[dict[str, Any]] = []
    subtitle_cues: list[SubtitleSegment] = []

    cursor_sec = 0.0
    sub_idx = 1

    for ch in chapters:
        cnum = int(ch["chapter_num"])
        ctitle = str(ch["title_fr"])
        ch_pause_len = max(0.25, chapter_pause)
        master_segments.append(np.zeros(int(ch_pause_len * SAMPLE_RATE), dtype=np.float32))
        sfx_events.append((cursor_sec + 0.1, _synthesize_soft_bell(523.25, 0.85, amp=0.11, sr=SAMPLE_RATE)))
        cursor_sec += ch_pause_len

        chapter_markers.append({
            "chapter_num": cnum,
            "chapter_id": ch.get("chapter_id", f"ch{cnum}"),
            "title_fr": ctitle,
            "start_sec": round(cursor_sec, 3),
        })

        for ev in ch.get("events", []):
            eid = ev["event_id"]
            etype = ev.get("type", "teacher")
            arr = decoded_clips[eid]
            dur = arr.size / SAMPLE_RATE
            ev_start = cursor_sec
            ev_end = ev_start + dur

            master_segments.append(arr)
            cursor_sec = ev_end

            gap_sec = inter_pause + extra_inter_pause
            master_segments.append(np.zeros(int(gap_sec * SAMPLE_RATE), dtype=np.float32))
            cursor_sec += gap_sec

            if etype == "teacher":
                speech_mask_ranges.append((ev_start, ev_end))
            elif etype == "audio_track":
                mute_pad_ranges.append((max(0.0, ev_start - 0.15), ev_end + 0.15))

            nar_text = str(ev.get("narration_fr") or (ev.get("board_data") or {}).get("heading") or "").strip()
            sents = _split_bilingual_sentences(nar_text) or ([nar_text] if nar_text else [])
            ev_caption_cues: list[dict[str, Any]] = []
            if sents and dur > 0.4:
                tot_chars = sum(max(1, len(s)) for s in sents)
                cur_s = ev_start
                for s_str in sents:
                    frac = max(1, len(s_str)) / tot_chars
                    s_dur = dur * frac
                    s_end = min(ev_end, cur_s + s_dur)
                    ev_caption_cues.append({"start": round(cur_s, 3), "end": round(s_end, 3), "text": s_str})
                    subtitle_cues.append(SubtitleSegment(index=sub_idx, start=cur_s, end=s_end, text=s_str))
                    sub_idx += 1
                    cur_s = s_end

            timeline_events.append({
                "event_id": eid,
                "chapter_num": cnum,
                "chapter_title": ctitle,
                "type": etype,
                "speaker": ev.get("speaker", "lehrerin"),
                "start_sec": round(ev_start, 3),
                "end_sec": round(ev_end + gap_sec, 3),
                "dur_sec": round(dur + gap_sec, 3),
                "board_mode": ev.get("board_mode", "BOOK_KEN_BURNS_SPOTLIGHT"),
                "board_data": ev.get("board_data", {}),
                "narration_fr": nar_text,
                "subtitle_de": str(ev.get("subtitle_de") or ""),
                "subtitle_ar": str(ev.get("subtitle_ar") or ""),
                "subtitle_pron": str(ev.get("subtitle_pron") or ""),
                "audio_rel_path": str(ev.get("audio_rel_path") or ""),
                "caption_cues": ev_caption_cues,
            })

    # Clean outro pad
    master_segments.append(np.zeros(int(2.0 * SAMPLE_RATE), dtype=np.float32))
    voice_track = np.concatenate(master_segments) if master_segments else np.zeros(SAMPLE_RATE, dtype=np.float32)
    total_samples = voice_track.size
    total_sec = total_samples / SAMPLE_RATE

    duck = np.ones(total_samples, dtype=np.float32)
    for rs, re_t in speech_mask_ranges:
        i0 = max(0, int(rs * SAMPLE_RATE))
        i1 = min(total_samples, int(re_t * SAMPLE_RATE))
        duck[i0:i1] = 0.22
    for ms, me in mute_pad_ranges:
        i0 = max(0, int(ms * SAMPLE_RATE))
        i1 = min(total_samples, int(me * SAMPLE_RATE))
        duck[i0:i1] = 0.0
    win = max(1, int(0.18 * SAMPLE_RATE))
    duck = _boxcar_smooth(duck, win)

    ambient = _build_academic_ambient(total_samples, sr=SAMPLE_RATE) * duck
    mix = voice_track + ambient
    for st_sec, bell in sfx_events:
        idx = int(st_sec * SAMPLE_RATE)
        end = min(total_samples, idx + bell.size)
        if end > idx:
            mix[idx:end] += bell[: end - idx]
    mix = np.clip(mix, -0.96, 0.96).astype(np.float32)

    spf = SAMPLE_RATE // fps
    n_frames = int(math.ceil(total_samples / spf))
    padded = np.zeros(n_frames * spf, dtype=np.float32)
    padded[:total_samples] = mix
    frames_rms = np.sqrt(np.mean(padded.reshape(n_frames, spf) ** 2, axis=1))
    norm_rms = np.clip((frames_rms / 0.22) * 1000.0, 0, 1000).astype(np.int32).tolist()

    m4a_path = out_dir / "master_2h.m4a"
    mp3_path = out_dir / "master_2h_full.mp3"
    podcast_path = out_dir / f"{lesson_id}_Rapid_Fluency_Podcast.mp3"
    tmp_mix = out_dir / "_tmp_master_mix.f32"
    mix.tofile(str(tmp_mix))
    ffmpeg = get_ffmpeg_exe()
    try:
        ff_cmd = [
            ffmpeg, "-y", "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", str(tmp_mix),
            "-ac", "2", "-ar", "44100", "-c:a", "aac", "-b:a", "192k", str(m4a_path),
        ]
        if not skip_full_mp3:
            ff_cmd += ["-ac", "2", "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "160k", str(mp3_path)]
        subprocess.run(ff_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    finally:
        tmp_mix.unlink(missing_ok=True)

    pod_info = _build_rapid_fluency_podcast(chapters, decoded_clips, podcast_path, sr=SAMPLE_RATE)

    tl_obj = {
        "course_title": cur.get("course_title", f"Unit {lesson_id}"),
        "lesson_id": lesson_id,
        "level": cur.get("level", ""),
        "lektion": cur.get("lektion", 0),
        "de_ratio": cur.get("de_ratio", 0.2),
        "de_pct": cur.get("de_pct", 20),
        "fps": fps,
        "total_duration_sec": round(total_sec, 3),
        "total_frames": n_frames,
        "chapters": chapter_markers,
        "events": timeline_events,
    }
    tl_path = out_dir / "timeline.json"
    tl_path.write_text(json.dumps(tl_obj, ensure_ascii=False), encoding="utf-8")

    rms_path = out_dir / "rms_per_frame.json"
    rms_path.write_text(json.dumps(norm_rms), encoding="utf-8")

    ass_path = write_ass_file(subtitle_cues, out_dir / "subtitles.ass", preset="educational", dual_language=False)
    srt_path = write_srt_file(subtitle_cues, out_dir / "subtitles.srt", use_translated=False)

    yt_lines = []
    for cm in chapter_markers:
        s = int(cm["start_sec"])
        hh, mm, ss = s // 3600, (s % 3600) // 60, s % 60
        yt_lines.append(f"{hh}:{mm:02d}:{ss:02d} — {cm['title_fr']}")
    yt_path = out_dir / "chapters.txt"
    yt_path.write_text("\n".join(yt_lines) + "\n", encoding="utf-8")

    summary = {
        "lesson_id": lesson_id,
        "total_duration_sec": round(total_sec, 2),
        "total_duration_min": round(total_sec / 60.0, 2),
        "total_events": len(timeline_events),
        "total_chapters": len(chapter_markers),
        "m4a": str(m4a_path),
        "mp3": str(mp3_path),
        **pod_info,
        "timeline": str(tl_path),
        "ass": str(ass_path),
        "srt": str(srt_path),
        "chapters_txt": str(yt_path),
    }
    print(f"LANG_AUDIO_PIPELINE_OK: {json.dumps(summary, ensure_ascii=False)}", flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Unit 2H+ Master Audio & Fluency Podcast")
    parser.add_argument("--curriculum", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--min-sec", type=float, default=TARGET_MIN_SEC)
    parser.add_argument("--dry-run", action="store_true", help="Skip external TTS API calls for offline timing smoke tests.")
    parser.add_argument("--no-full-mp3", action="store_true", help="Skip redundant 2H MP3 duplicate (keeps M4A + Rapid Podcast MP3).")
    parser.add_argument("--piper-dir", type=Path, default=None, help="Cache dir for offline Piper ONNX voices.")
    args = parser.parse_args()
    build_menschen_audio_and_timeline(
        args.curriculum,
        args.assets_dir,
        args.out_dir,
        fps=args.fps,
        max_tts_workers=args.workers,
        min_duration_sec=args.min_sec,
        skip_tts_synthesis=args.dry_run,
        skip_full_mp3=args.no_full_mp3,
        piper_dir=args.piper_dir,
    )


if __name__ == "__main__":
    main()
