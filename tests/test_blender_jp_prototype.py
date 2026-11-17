"""Smoke & structural checks for Blender 3D Japanese prototype pipeline."""

from __future__ import annotations

import json
import py_compile
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aegis_studio.blender_jp_studio import (
    DEFAULT_JP_CARDS,
    partition_frame_ranges,
    prepare_blender_bundle,
)


def test_blender_jp_syntax_and_workflow() -> None:
    py_compile.compile(str(ROOT / "aegis_studio" / "blender_jp_studio.py"), doraise=True)
    py_compile.compile(str(ROOT / "aegis_studio" / "blender_jp_scene.py"), doraise=True)

    wf = (ROOT / ".github" / "workflows" / "blender-3d-jp.yml").read_text(encoding="utf-8")
    assert "blender-4.2.3-linux-x64.tar.xz" in wf
    assert "AISTUDIO_KEYS_JSON" in wf
    assert "blender_jp_scene.py" in wf

    ranges = partition_frame_ranges(103, 4)
    assert ranges == [(1, 26), (27, 52), (53, 78), (79, 103)]
    print("[PASS] test_blender_jp_syntax_and_workflow")


def test_blender_jp_prepare_dry_run() -> None:
    with tempfile.TemporaryDirectory() as td:
        work_dir = Path(td) / "jp_prep"
        mp = prepare_blender_bundle(work_dir, topic="", width=1280, height=720, fps=24, samples=16, dry_run=True)
        m = json.loads(mp.read_text(encoding="utf-8"))
        assert len(m["acts"]) == len(DEFAULT_JP_CARDS) == 3
        assert (work_dir / m["master_audio"]).exists()
        for act in m["acts"]:
            png_p = work_dir / act["card_png"]
            assert png_p.exists() and png_p.stat().st_size > 20_000, f"Bad glass card PNG: {png_p}"
        print(f"[PASS] test_blender_jp_prepare_dry_run: frames={m['total_frames']} acts={len(m['acts'])}")


if __name__ == "__main__":
    test_blender_jp_syntax_and_workflow()
    test_blender_jp_prepare_dry_run()
    print("ALL_BLENDER_JP_TESTS_PASSED")
