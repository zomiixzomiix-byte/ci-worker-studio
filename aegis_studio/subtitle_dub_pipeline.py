"""AEGIS-Native Cloud Video Pull (yt-dlp), Audio Extraction, Translation, ASS Subtitling & Multi-Voice Dubbing."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .aegis_client import AegisStudioClient
from .ass_subtitles import SubtitleSegment, write_ass_file, write_srt_file
from .ffmpeg_utils import (
    best_h264_video_flags,
    download_source_video,
    escape_ffmpeg_filter_path,
    extract_clean_wav16k,
    get_ffmpeg_exe,
    probe_media_info,
    save_tts_audio_normalized,
)


def _transcribe_with_faster_whisper(wav_path: Path, model_size: str = "large-v3") -> list[SubtitleSegment]:
    """Optional GPU Whisper path when --asr whisper is selected on Kaggle T4."""
    from faster_whisper import WhisperModel  # type: ignore

    device, compute_type = "cpu", "int8"
    try:
        import ctranslate2  # type: ignore

        if ctranslate2.get_cuda_device_count() > 0:
            device, compute_type = "cuda", "float16"
    except Exception:
        pass

    print(f"[WHISPER] Loading '{model_size}' on {device} ({compute_type})...", flush=True)
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    raw_segs, info = model.transcribe(
        str(wav_path),
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
        word_timestamps=True,
        beam_size=5,
    )
    print(f"[WHISPER] Language={getattr(info, 'language', '?')} ({getattr(info, 'language_probability', 0):.2f})", flush=True)

    segments: list[SubtitleSegment] = []
    for idx, seg in enumerate(raw_segs, start=1):
        txt = (seg.text or "").strip()
        if not txt:
            continue
        words = [
            {"start": float(w.start), "end": float(w.end), "word": str(w.word)}
            for w in (getattr(seg, "words", None) or [])
        ]
        segments.append(SubtitleSegment(index=idx, start=float(seg.start), end=float(seg.end), text=txt, words=words))
    return segments


def _extract_and_translate_with_aegis(
    client: AegisStudioClient,
    wav_path: Path,
    work_dir: Path,
    duration: float,
    target_lang: str,
) -> tuple[list[SubtitleSegment], dict[int, str]]:
    """
    100% AEGIS-Native Audio Pull + Context-Aware Idiomatic Translation in one multimodal pass.
    Returns timed SubtitleSegments (with speaker tags mapped cleanly) and per-segment speaker labels.
    """
    exe = get_ffmpeg_exe()
    chunk_sec = 90.0
    total_chunks = max(1, int((duration + chunk_sec - 1) // chunk_sec))
    segments: list[SubtitleSegment] = []
    speaker_map: dict[int, str] = {}
    wants_trans = bool(target_lang and target_lang.lower() not in ("none", "keep", "original"))

    sys_p = (
        "You are an expert cinematic subtitler & audio director.\n"
        "Listen carefully to tone, speaker transitions, and natural speech rhythm.\n"
        "Return STRICT JSON ONLY."
    )

    for idx in range(total_chunks):
        start_at = idx * chunk_sec
        dur = min(chunk_sec, max(1.0, duration - start_at))
        chunk_mp3 = work_dir / f"aegis_listen_{idx:03d}.mp3"
        subprocess.run(
            [exe, "-y", "-ss", f"{start_at:.2f}", "-t", f"{dur:.2f}", "-i", str(wav_path), "-ac", "1", "-ar", "16000", "-b:a", "48k", str(chunk_mp3)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        b64 = base64.b64encode(chunk_mp3.read_bytes()).decode("ascii")
        trans_instr = (
            f'Also write an engaging, idiomatic "{target_lang}" subtitle/dubbing translation in `translated_text`.'
            if wants_trans
            else 'Leave `translated_text` as "".'
        )
        user_p = (
            f"Transcribe all spoken speech in this audio clip with accurate relative timestamps (0.0 to {dur:.1f}s).\n"
            f"Tag each speaker as 'M1'/'M2' (male) or 'F1'/'F2' (female) in `speaker`.\n"
            f"{trans_instr}\n"
            f"Return JSON:\n"
            f'{{"segments": [{{"start": 0.4, "end": 3.8, "speaker": "M1", "text": "original phrase", "translated_text": "..."}}]}}'
        )
        res = client.generate_json(
            sys_p,
            user_p,
            max_output_tokens=16384,
            thinking_budget=1024,
            temperature=0.2,
            extra_parts=[{"inlineData": {"mimeType": "audio/mp3", "data": b64}}],
        )
        for item in res["data"].get("segments", []):
            txt = str(item.get("text") or "").strip()
            tr_txt = str(item.get("translated_text") or "").strip()
            if not (txt or tr_txt):
                continue
            s_abs = max(0.0, start_at + float(item.get("start") or 0.0))
            e_abs = max(s_abs + 0.45, start_at + float(item.get("end") or (float(item.get("start") or 0.0) + 2.2)))
            seg_id = len(segments) + 1
            segments.append(
                SubtitleSegment(index=seg_id, start=s_abs, end=e_abs, text=txt or tr_txt, translated_text=tr_txt)
            )
            speaker_map[seg_id] = str(item.get("speaker") or "M1").upper().strip()
        print(f"[AEGIS LISTEN] Chunk {idx + 1}/{total_chunks} -> {len(segments)} total cues ({res.get('model')})", flush=True)
    return segments, speaker_map


def translate_segments_contextually(
    client: AegisStudioClient,
    segments: list[SubtitleSegment],
    target_lang: str,
    batch_size: int = 20,
) -> list[SubtitleSegment]:
    """Translate remaining untranslated segments in sliding-context batches via AEGIS Quality Mix."""
    pending = [s for s in segments if not s.translated_text.strip()]
    if not pending or not target_lang or target_lang.lower() in ("none", "keep", "original"):
        return segments

    sys_prompt = (
        f"You are an elite cinematic translator to engaging, idiomatic {target_lang}.\n"
        f"Keep subtitles punchy, emotionally faithful, and comfortable to read. Output STRICT JSON."
    )
    for start_i in range(0, len(pending), batch_size):
        batch = pending[start_i : start_i + batch_size]
        prev_ctx = [s.text for s in segments[max(0, batch[0].index - 4) : batch[0].index - 1]]
        payload = [{"id": s.index, "duration_sec": round(s.end - s.start, 2), "text": s.text} for s in batch]
        user_prompt = (
            f"Context before: {json.dumps(prev_ctx, ensure_ascii=False)}\n"
            f"Translate EVERY item in `items` into {target_lang}.\n"
            f'Format: {{"translations": [{{"id": 1, "text": "..."}}]}}\n\n'
            f"items = {json.dumps(payload, ensure_ascii=False)}"
        )
        res = client.generate_json(sys_prompt, user_prompt, max_output_tokens=16384, thinking_budget=1024, temperature=0.2)
        by_id = {int(t["id"]): str(t["text"]).strip() for t in res["data"].get("translations", []) if "id" in t and "text" in t}
        for s in batch:
            s.translated_text = by_id.get(s.index, s.text)
        print(f"[TRANSLATE] Batch {start_i + 1}-{min(len(pending), start_i + batch_size)}/{len(pending)} via {res.get('model')}", flush=True)
    return segments


def _resolve_speaker_voice(speaker_tag: str, default_voice: str, multi_voice: bool) -> str:
    if not multi_voice:
        return default_voice
    tag = (speaker_tag or "").upper()
    if tag.startswith("F"):
        return "Kore" if tag.endswith("2") else "Aoede"
    if tag.endswith("2"):
        return "Puck" if default_voice != "Puck" else "Fenrir"
    return default_voice


def build_dubbed_audio_track(
    client: AegisStudioClient,
    segments: list[SubtitleSegment],
    speaker_map: dict[int, str],
    orig_video: Path,
    work_dir: Path,
    out_mp3: Path,
    voice_name: str = "Charon",
    multi_voice: bool = True,
    total_duration: float = 0.0,
) -> Path | None:
    """Synthesize multi-speaker AEGIS Free TTS audio aligned cleanly with background ducking."""
    exe = get_ffmpeg_exe()
    tts_dir = work_dir / "dub_tts"
    tts_dir.mkdir(parents=True, exist_ok=True)
    active_segs = [s for s in segments if (s.translated_text or s.text).strip()]
    if not active_segs:
        return None

    def _make_one(seg: SubtitleSegment) -> tuple[SubtitleSegment, Path]:
        line = (seg.translated_text or seg.text).strip()
        v = _resolve_speaker_voice(speaker_map.get(seg.index, "M1"), voice_name, multi_voice)
        raw_bytes, _mime, _m = client.synthesize_tts(line, voice_name=v)
        raw_mp3 = tts_dir / f"seg_{seg.index:04d}_raw.mp3"
        save_tts_audio_normalized(raw_bytes, raw_mp3)
        dur = float(probe_media_info(raw_mp3)["duration"] or 0.0)
        slot = max(0.85, seg.end - seg.start)
        fitted = tts_dir / f"seg_{seg.index:04d}_fit.wav"
        if dur > slot * 1.03:
            ratio = min(1.26, max(1.0, dur / slot))
            subprocess.run(
                [exe, "-y", "-i", str(raw_mp3), "-filter:a", f"atempo={ratio:.3f}", "-ar", "48000", "-ac", "2", str(fitted)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        else:
            subprocess.run(
                [exe, "-y", "-i", str(raw_mp3), "-ar", "48000", "-ac", "2", str(fitted)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
        return seg, fitted

    print(f"[DUB] Synthesizing {len(active_segs)} lines via AEGIS Free TTS (multi_voice={multi_voice})...", flush=True)
    fitted_items: list[tuple[SubtitleSegment, Path]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(_make_one, s) for s in active_segs]
        for fut in concurrent.futures.as_completed(futs):
            fitted_items.append(fut.result())
    fitted_items.sort(key=lambda x: x[0].start)

    batch_wavs: list[Path] = []
    for b_idx in range(0, len(fitted_items), 40):
        chunk = fitted_items[b_idx : b_idx + 40]
        cmd = [exe, "-y"]
        fc_parts: list[str] = []
        mix_labels: list[str] = []
        for i, (seg, wav_p) in enumerate(chunk):
            cmd.extend(["-i", str(wav_p)])
            delay_ms = max(0, int(round(seg.start * 1000)))
            fc_parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[d{i}]")
            mix_labels.append(f"[d{i}]")
        out_batch = tts_dir / f"dub_batch_{b_idx // 40}.wav"
        fc = ";".join(fc_parts) + f";{''.join(mix_labels)}amix=inputs={len(chunk)}:normalize=0:dropout_transition=0[aout]"
        cmd.extend(["-filter_complex", fc, "-map", "[aout]", "-ar", "48000", "-ac", "2", str(out_batch)])
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        batch_wavs.append(out_batch)

    full_dub_wav = batch_wavs[0] if len(batch_wavs) == 1 else (tts_dir / "full_dub.wav")
    if len(batch_wavs) > 1:
        cmd = [exe, "-y"]
        for bw in batch_wavs:
            cmd.extend(["-i", str(bw)])
        lbls = "".join(f"[{i}:a]" for i in range(len(batch_wavs)))
        cmd.extend(["-filter_complex", f"{lbls}amix=inputs={len(batch_wavs)}:normalize=0[aout]", "-map", "[aout]", "-ar", "48000", "-ac", "2", str(full_dub_wav)])
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # Export clean standalone voice/podcast MP3 alongside mixed video soundtrack
    subprocess.run(
        [exe, "-y", "-i", str(full_dub_wav), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:a", "libmp3lame", "-b:a", "192k", str(out_mp3)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )

    final_m4a = work_dir / "dubbed_master_audio.m4a"
    dur_arg = ["-t", f"{total_duration:.2f}"] if total_duration > 0 else []
    fc_duck = (
        "[1:a]asplit=2[voice][sc];"
        "[0:a][sc]sidechaincompress=threshold=0.02:ratio=6:attack=80:release=450[bg];"
        "[bg][voice]amix=inputs=2:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[out]"
    )
    mix_res = subprocess.run(
        [exe, "-y", "-i", str(orig_video), "-i", str(full_dub_wav), "-filter_complex", fc_duck, "-map", "[out]", *dur_arg, "-c:a", "aac", "-b:a", "192k", str(final_m4a)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if mix_res.returncode != 0:
        subprocess.run([exe, "-y", "-i", str(full_dub_wav), *dur_arg, "-c:a", "aac", "-b:a", "192k", str(final_m4a)], check=True)
    return final_m4a


def run_subtitle_dub_pipeline(
    video_input: str,
    out_dir: Path,
    target_lang: str = "العربية",
    preset: str = "cinema",
    asr_engine: str = "aegis",
    dual_language: bool = False,
    karaoke: bool = False,
    enable_dubbing: bool = False,
    voice_name: str = "Charon",
    multi_voice: bool = True,
    whisper_model: str = "large-v3",
    client: AegisStudioClient | None = None,
) -> dict[str, Any]:
    """Pull video (URL/YouTube/local) -> AEGIS extract & translate -> Cinema ASS + Neural Dubbing."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)
    aegis = client or AegisStudioClient()

    local_video = download_source_video(video_input, work_dir)
    info = probe_media_info(local_video)
    wav16 = extract_clean_wav16k(local_video, work_dir / "audio_16k.wav")
    extracted_audio_mp3 = out_dir / f"{local_video.stem}_extracted_audio.mp3"
    subprocess.run(
        [get_ffmpeg_exe(), "-y", "-i", str(wav16), "-c:a", "libmp3lame", "-b:a", "160k", str(extracted_audio_mp3)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )

    speaker_map: dict[int, str] = {}
    if asr_engine == "whisper":
        try:
            segments = _transcribe_with_faster_whisper(wav16, model_size=whisper_model)
            translate_segments_contextually(aegis, segments, target_lang=target_lang)
        except Exception as exc:
            print(f"[ASR] Whisper unavailable ({exc}); switching to AEGIS Multimodal Pull...", flush=True)
            segments, speaker_map = _extract_and_translate_with_aegis(
                aegis, wav16, work_dir, float(info["duration"] or 60.0), target_lang
            )
    else:
        segments, speaker_map = _extract_and_translate_with_aegis(
            aegis, wav16, work_dir, float(info["duration"] or 60.0), target_lang
        )
        translate_segments_contextually(aegis, segments, target_lang=target_lang)

    stem = local_video.stem
    ass_path = write_ass_file(
        segments,
        out_dir / f"{stem}.ass",
        video_width=int(info["width"]),
        video_height=int(info["height"]),
        preset=preset,
        dual_language=dual_language,
        karaoke=karaoke,
    )
    srt_path = write_srt_file(segments, out_dir / f"{stem}.srt", use_translated=True)

    dub_audio: Path | None = None
    dub_mp3: Path | None = None
    if enable_dubbing:
        dub_mp3 = out_dir / f"{stem}_dubbed_audio.mp3"
        dub_audio = build_dubbed_audio_track(
            aegis,
            segments,
            speaker_map,
            local_video,
            work_dir,
            dub_mp3,
            voice_name=voice_name,
            multi_voice=multi_voice,
            total_duration=float(info["duration"] or 0.0),
        )

    out_mp4 = out_dir / f"{stem}_studio_final.mp4"
    exe = get_ffmpeg_exe()
    ass_esc = escape_ffmpeg_filter_path(ass_path)
    cmd = [exe, "-y", "-i", str(local_video)]
    if dub_audio and dub_audio.exists():
        cmd.extend(["-i", str(dub_audio), "-map", "0:v:0", "-map", "1:a:0"])
    else:
        cmd.extend(["-map", "0:v:0", "-map", "0:a?"])
    cmd.extend(["-vf", f"ass='{ass_esc}'", *best_h264_video_flags("cinema")])
    if not dub_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    else:
        cmd.extend(["-c:a", "copy"])
    cmd.extend(["-movflags", "+faststart", str(out_mp4)])
    subprocess.run(cmd, check=True)

    return {
        "video": str(out_mp4),
        "ass": str(ass_path),
        "srt": str(srt_path),
        "extracted_audio_mp3": str(extracted_audio_mp3),
        "dub_audio_mp3": str(dub_mp3) if dub_mp3 and dub_mp3.exists() else None,
        "segments_count": len(segments),
        "asr_engine": asr_engine,
        "client_mode": aegis.mode,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AEGIS-Native Video Pull, Extract, Translate & Neural Dub Studio")
    parser.add_argument("--video", required=True, help="YouTube/social URL, direct HTTP video URL, or local file path")
    parser.add_argument("--out-dir", default="output/subtitled")
    parser.add_argument("--target-lang", default="العربية")
    parser.add_argument("--preset", default="cinema", choices=["cinema", "box", "shorts", "educational"])
    parser.add_argument("--asr", default="aegis", choices=["aegis", "whisper"], help="aegis=Direct Gemini audio pull & translate; whisper=GPU faster-whisper")
    parser.add_argument("--dual", action="store_true", help="Include original text above translation")
    parser.add_argument("--karaoke", action="store_true")
    parser.add_argument("--dub", action="store_true", help="Synthesize neural dubbed soundtrack via AEGIS TTS")
    parser.add_argument("--voice", default="Charon", help="Primary voice (Charon, Aoede, Puck, Kore, Fenrir)")
    parser.add_argument("--single-voice", action="store_true", help="Disable multi-speaker cast switching")
    parser.add_argument("--whisper-model", default="large-v3")
    args = parser.parse_args()

    res = run_subtitle_dub_pipeline(
        video_input=args.video,
        out_dir=Path(args.out_dir),
        target_lang=args.target_lang,
        preset=args.preset,
        asr_engine=args.asr,
        dual_language=args.dual,
        karaoke=args.karaoke,
        enable_dubbing=args.dub,
        voice_name=args.voice,
        multi_voice=not args.single_voice,
        whisper_model=args.whisper_model,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
