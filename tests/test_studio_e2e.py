"""Automated Unit + Full Live AEGIS-Native Audio Pull/Translate + Multi-Voice Motion Studio E2E Suite."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aegis_studio.aegis_client import (
    AegisStudioClient,
    QUALITY_FLAGSHIP_CHAIN,
    _adapt_thinking_config,
    is_strong_flagship_model,
)
from aegis_studio.ass_subtitles import SubtitleSegment, format_ass_time, wrap_balanced_lines, write_ass_file, write_srt_file
from aegis_studio.ffmpeg_utils import (
    escape_ffmpeg_filter_path,
    extract_clean_wav16k,
    get_ffmpeg_exe,
    probe_media_info,
    save_tts_audio_normalized,
)
from aegis_studio.motion_video_pipeline import run_motion_video_pipeline
from aegis_studio.subtitle_dub_pipeline import _extract_and_translate_with_aegis


def test_quality_mix_client_logic() -> None:
    keys_payload = json.dumps([f"fake-key-{i}" for i in range(1, 6)])
    c = AegisStudioClient(base_url="http://127.0.0.1:59999", keys_json=keys_payload)
    assert c.mode == "standalone" and len(c.keys) == 5

    leads = [c.next_quality_chain()[0] for _ in range(5)]
    assert leads == [
        "gemini-4-hydrogen",
        "gemini-4-hydrogen",
        "gemini-3-flash-preview",
        "gemini-4-hydrogen",
        "gemini-3-flash-preview",
    ]
    assert QUALITY_FLAGSHIP_CHAIN.index("gemini-3-flash-preview") < QUALITY_FLAGSHIP_CHAIN.index("gemini-3.6-flash")
    assert is_strong_flagship_model("gemini-4-hydrogen")
    assert is_strong_flagship_model("gemini-3-flash-preview")
    assert not is_strong_flagship_model("gemini-3.5-flash-lite")
    assert not is_strong_flagship_model("gemini-2.5-flash")

    picked = [c._pick_standalone_key("gemini-4-hydrogen", set())["id"] for _ in range(6)]
    assert picked == ["k_1", "k_2", "k_3", "k_4", "k_5", "k_1"]

    cfg = {"thinkingConfig": {"includeThoughts": True, "thinkingBudget": 4096}}
    _adapt_thinking_config(cfg, "gemini-3.6-flash")
    assert cfg["thinkingConfig"]["thinkingLevel"] == "HIGH"
    assert "thinkingBudget" not in cfg["thinkingConfig"]
    assert shutil.which("yt-dlp") is not None, "yt-dlp expected on system"
    print("[PASS] test_quality_mix_client_logic")


def test_ass_subtitle_and_cloud_manifests() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        assert format_ass_time(3661.25) == "1:01:01.25"
        wrapped = wrap_balanced_lines("مرحبا بكم في اختبار الترجمة السحابية عالية الدقة باللغة العربية", max_chars=26)
        assert "\\N" in wrapped

        segs = [
            SubtitleSegment(
                index=1,
                start=0.2,
                end=2.6,
                text="Cloud rendering prevents laptop overheating.",
                translated_text="المعالجة السحابية تمنع تسخين الحاسوب تماماً.",
            )
        ]
        ass_p = write_ass_file(segs, tmp / "sample.ass", preset="cinema", dual_language=True)
        srt_p = write_srt_file(segs, tmp / "sample.srt")
        ass_txt = ass_p.read_text(encoding="utf-8-sig")
        assert "Style: Main," in ass_txt and "Style: Original," in ass_txt
        assert "Dialogue: 1,0:00:00.20,0:00:02.60,Main" in ass_txt
        assert "المعالجة السحابية" in srt_p.read_text(encoding="utf-8")

    nb = json.loads((ROOT / "cloud" / "kaggle_video_studio.ipynb").read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4 and len(nb["cells"]) >= 5
    wf = (ROOT / ".github" / "workflows" / "cloud-video-studio.yml").read_text(encoding="utf-8")
    assert "AISTUDIO_KEYS_JSON" in wf and "--asr aegis" in wf
    bf = (ROOT / ".github" / "workflows" / "batch-factory.yml").read_text(encoding="utf-8")
    assert "max-parallel: 4" in bf and "queue/jobs.json" in bf
    q = json.loads((ROOT / "queue" / "jobs.json").read_text(encoding="utf-8"))
    assert isinstance(q.get("jobs"), list) and len(q["jobs"]) >= 1

    sys.path.insert(0, str(ROOT / "tools"))
    import cloud_cli
    st = cloud_cli.get_status()
    assert st["gh_installed"] is True and st["vault_keys_ready"] == 61
    print("[PASS] test_ass_subtitle_and_cloud_manifests")


def test_live_aegis_full_video_and_audio_pull() -> None:
    """Live E2E: AEGIS 2-scene storytelling storyboard + 2-voice TTS + SFX soundbed + 1080p MP4 + AEGIS Multimodal Audio Pull."""
    gw_url = os.environ.get("AEGIS_BASE_URL", "http://127.0.0.1:20128")
    client = AegisStudioClient(base_url=gw_url)
    assert client.mode == "gateway", f"Expected live AEGIS gateway on {gw_url}"

    # 1. Build engaging 2-scene storyboard (hook_impact + versus_comparison, 2 voices) via AEGIS
    sb_res = client.generate_json(
        "Return strict JSON only.",
        (
            'Generate 2 short, punchy demo scenes in Arabic about "الذكاء الاصطناعي في الفيديو". '
            'Scene 1: layout="hook_impact", voice_name="Charon", narration_script max 8 words. '
            'Scene 2: layout="versus_comparison", voice_name="Aoede", narration_script max 8 words, with 2 comparison cards and minimal <svg viewBox="0 0 360 360">...</svg>. '
            'Format: {"scenes":[{"scene_id":1,"layout":"hook_impact","kicker":"HOOK","title":"...","subtitle":"...","voice_name":"Charon","narration_script":"...","cards":[{"metric":"2×","label":"...","detail":"..."}],"svg_graphic":""},{"scene_id":2,...}]}'
        ),
        max_output_tokens=6000,
        thinking_budget=1024,
    )
    scenes = sb_res["data"]["scenes"]
    assert len(scenes) == 2
    assert is_strong_flagship_model(sb_res["model"])

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td) / "studio_out"
        sb_path = Path(td) / "sb.json"
        sb_path.write_text(json.dumps({"scenes": scenes}, ensure_ascii=False), encoding="utf-8")

        # 2. Render 1920x1080 30fps MP4 + 2 voices (Charon + Aoede) + subtle SFX/soundbed + podcast MP3
        res = run_motion_video_pipeline(
            storyboard_file=sb_path,
            out_dir=out_dir,
            width=1920,
            height=1080,
            fps=30,
            with_captions=True,
            with_sfx=True,
            force_cpu=True,
            client=client,
        )
        mp4_path = Path(res["video"])
        mp3_path = Path(res["audio_podcast_mp3"])
        assert mp4_path.exists() and mp4_path.stat().st_size > 25000
        assert mp3_path.exists() and mp3_path.stat().st_size > 15000
        info = probe_media_info(mp4_path)
        assert info["width"] == 1920 and info["height"] == 1080 and float(info["duration"]) >= 4.0

        # 3. Verify AEGIS-Native Audio Pull & English Translation directly from that rendered video's audio!
        wav16 = extract_clean_wav16k(mp4_path, Path(td) / "pull.wav")
        pulled_segs, speaker_map = _extract_and_translate_with_aegis(
            client, wav16, Path(td), float(info["duration"]), target_lang="English"
        )
        assert len(pulled_segs) >= 1, "AEGIS audio pull returned 0 segments"
        assert any(s.translated_text.strip() for s in pulled_segs), "Missing English translation from AEGIS audio pull"

        # 4. Also verify burning the AEGIS-extracted .ass onto a trimmed clip succeeds cleanly
        ass_test = write_ass_file(pulled_segs[:2], Path(td) / "pulled.ass", preset="cinema", dual_language=True)
        burned = Path(td) / "burned.mp4"
        subprocess.run(
            [
                get_ffmpeg_exe(), "-y", "-i", str(mp4_path), "-t", "3",
                "-vf", f"ass='{escape_ffmpeg_filter_path(ass_test)}'",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-c:a", "copy", str(burned),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        assert burned.exists() and burned.stat().st_size > 15000
        print(
            f"[PASS] test_live_aegis_full_video_and_audio_pull | model={sb_res['model']} "
            f"| res={info['width']}x{info['height']} | dur={info['duration']:.2f}s "
            f"| pulled_cues={len(pulled_segs)} | speakers={list(set(speaker_map.values()))}"
        )


if __name__ == "__main__":
    test_quality_mix_client_logic()
    test_ass_subtitle_and_cloud_manifests()
    test_live_aegis_full_video_and_audio_pull()
    print("ALL_AEGIS_NATIVE_STUDIO_TESTS_PASSED")
