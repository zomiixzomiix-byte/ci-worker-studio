"""Pure Blender 4.2 Procedural 3D Japanese Zen Studio Scene & Cycles Sharded Renderer.

Executed exclusively by Blender:
  blender -b -P aegis_studio/blender_jp_scene.py -- \
    --manifest work/manifest.json --start-frame 1 --end-frame 160 --out-dir work/frames
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from pathlib import Path


def _hex_to_rgba(hex_str: str, alpha: float = 1.0) -> tuple[float, float, float, float]:
    h = hex_str.lstrip("#")
    if len(h) != 6:
        return (0.22, 0.74, 0.97, alpha)
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return (r ** 2.2, g ** 2.2, b ** 2.2, alpha)


def _find_japanese_font() -> str | None:
    """Locate a verified Japanese TTF/OTF/TTC font cleanly for Blender 3D Text curves."""
    explicit_candidates = [
        "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
        "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        "/usr/share/fonts/truetype/takao-gothic/TakaoPGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansJP-Bold.ttf",
        r"C:\Windows\Fonts\YuGothB.ttc",
        r"C:\Windows\Fonts\meiryob.ttc",
    ]
    for cand in explicit_candidates:
        if os.path.exists(cand):
            return cand
    for query in ("IPAexGothic", "IPAPGothic", "TakaoPGothic", "Noto Sans CJK JP:style=Bold", ":lang=ja"):
        try:
            out = subprocess.check_output(["fc-match", query, "-f", "%{file}"], text=True).strip()
            if out and os.path.exists(out):
                return out
        except Exception:
            pass
    return None


def _parse_blender_args() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--start-frame", type=int, default=1)
    parser.add_argument("--end-frame", type=int, default=0)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--engine", default="cycles", choices=["cycles", "eevee"])
    return parser.parse_args(argv)


def _disable_mis_sampling(mat) -> None:
    """Prevent Cycles from wasting ray bounces sampling decorative glowing meshes as direct lights."""
    try:
        if hasattr(mat, "cycles") and hasattr(mat.cycles, "emission_sampling"):
            mat.cycles.emission_sampling = "NONE"
    except Exception:
        pass


def _make_principled_mat(
    name: str,
    color: tuple[float, float, float, float],
    metallic: float = 0.0,
    roughness: float = 0.35,
    emission_col: tuple[float, float, float, float] | None = None,
    emission_str: float = 0.0,
    disable_mis: bool = False,
):
    import bpy

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission_col is not None and emission_str > 0:
        bsdf.inputs["Emission Color"].default_value = emission_col
        bsdf.inputs["Emission Strength"].default_value = emission_str
    if disable_mis:
        _disable_mis_sampling(mat)
    return mat


def _make_card_texture_mat(name: str, png_path: str):
    import bpy

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.15
    bsdf.inputs["Emission Strength"].default_value = 1.05

    tex = nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(png_path, check_existing=True)
    tex.extension = "CLIP"

    links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    _disable_mis_sampling(mat)
    return mat


def _keyframe_act_visibility(obj, sf: int, ef: int, total_frames: int) -> None:
    """Strictly hide inactive-act objects so zero stray scale dots appear outside their window."""
    if sf > 1:
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_render", frame=1)
        obj.keyframe_insert(data_path="hide_render", frame=sf - 1)
    obj.hide_render = False
    obj.keyframe_insert(data_path="hide_render", frame=sf)
    obj.keyframe_insert(data_path="hide_render", frame=ef)
    if ef < total_frames:
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_render", frame=ef + 1)


def _build_and_render() -> None:
    import bpy
    from mathutils import Euler

    args = _parse_blender_args()
    manifest_p = Path(args.manifest).resolve()
    base_dir = manifest_p.parent
    m = json.loads(manifest_p.read_text(encoding="utf-8"))

    fps = int(m.get("fps", 24))
    width = int(m.get("width", 1280))
    height = int(m.get("height", 720))
    samples = int(m.get("samples", 16))
    total_frames = int(m.get("total_frames", 72))
    acts = m["acts"]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    if args.engine == "eevee":
        scene.render.engine = "BLENDER_EEVEE_NEXT"
        scene.eevee.taa_render_samples = max(4, min(16, samples))
    else:
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = max(4, samples)
        scene.cycles.use_adaptive_sampling = True
        scene.cycles.adaptive_threshold = 0.09
        scene.cycles.use_denoising = True
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
        scene.cycles.max_bounces = 1
        scene.cycles.diffuse_bounces = 1
        scene.cycles.glossy_bounces = 1
        scene.cycles.transmission_bounces = 0
        scene.cycles.volume_bounces = 0
        scene.cycles.transparent_max_bounces = 2
        scene.cycles.sample_clamp_indirect = 2.0

    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.frame_start = 1
    scene.frame_end = total_frames
    scene.view_settings.view_transform = "AgX"

    # Deep serene night/zen world background
    world = bpy.data.worlds.new("ZenWorld")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.015, 0.022, 0.045, 1.0)
    bg.inputs["Strength"].default_value = 0.8

    # Obsidian reflective studio stage floor
    bpy.ops.mesh.primitive_plane_add(size=28, location=(0, 0, 0))
    floor = bpy.context.active_object
    floor.name = "StudioFloor"
    floor.data.materials.append(_make_principled_mat("FloorMat", (0.018, 0.024, 0.042, 1.0), metallic=0.15, roughness=0.22))

    # Minimalist Japanese Torii / Architectural Shoji Backdrop
    torii_mat = _make_principled_mat("ToriiCedar", (0.06, 0.018, 0.02, 1.0), metallic=0.1, roughness=0.45)
    shoji_glow_mat = _make_principled_mat(
        "ShojiScreen", (0.95, 0.55, 0.25, 1.0), roughness=0.8,
        emission_col=(1.0, 0.42, 0.16, 1.0), emission_str=1.6,
        disable_mis=True,
    )
    beam_specs = [
        ((-1.95, 2.2, 1.85), (0.14, 0.14, 3.7)),
        ((1.95, 2.2, 1.85), (0.14, 0.14, 3.7)),
        ((0.0, 2.2, 3.55), (5.4, 0.2, 0.22)),
        ((0.0, 2.2, 2.95), (4.4, 0.14, 0.14)),
    ]
    for idx, (loc, scale) in enumerate(beam_specs):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
        b = bpy.context.active_object
        b.name = f"ToriiBeam_{idx}"
        b.scale = scale
        b.data.materials.append(torii_mat)

    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, 2.55, 1.7), rotation=(math.radians(90), 0, 0))
    shoji = bpy.context.active_object
    shoji.scale = (3.4, 2.9, 1.0)
    shoji.data.materials.append(shoji_glow_mat)

    # Floating glowing Sakura / Gold Zen dust spheres (MIS disabled for blazing-fast Cycles)
    orb_mats = [
        _make_principled_mat("OrbWarm", (1, 0.5, 0.3, 1), emission_col=(1.0, 0.52, 0.22, 1), emission_str=5.5, disable_mis=True),
        _make_principled_mat("OrbCool", (0.3, 0.7, 1.0, 1), emission_col=(0.3, 0.75, 1.0, 1), emission_str=4.5, disable_mis=True),
    ]
    for i in range(14):
        ang = i * 0.65
        rad = 2.6 + (i % 5) * 0.65
        z0 = 0.55 + (i % 7) * 0.44
        x0 = math.cos(ang) * rad - 0.3
        y0 = math.sin(ang) * rad + 0.6
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.035 + (i % 3) * 0.018, location=(x0, y0, z0))
        orb = bpy.context.active_object
        orb.data.materials.append(orb_mats[i % 2])
        orb.keyframe_insert(data_path="location", frame=1)
        orb.location = (x0 + math.sin(i) * 0.35, y0, z0 + 0.45)
        orb.keyframe_insert(data_path="location", frame=total_frames)

    # Studio 3-Point Lighting
    bpy.ops.object.light_add(type="AREA", location=(-3.2, -3.5, 3.6))
    key_l = bpy.context.active_object
    key_l.data.energy = 340
    key_l.data.size = 2.8
    key_l.data.color = (1.0, 0.91, 0.80)
    key_l.rotation_euler = Euler((math.radians(52), 0, math.radians(-38)), "XYZ")

    bpy.ops.object.light_add(type="AREA", location=(2.6, 1.2, 2.8))
    rim_l = bpy.context.active_object
    rim_l.data.energy = 420
    rim_l.data.size = 2.2
    rim_l.rotation_euler = Euler((math.radians(65), 0, math.radians(135)), "XYZ")

    bpy.ops.object.light_add(type="AREA", location=(-1.4, -4.0, 1.4))
    fill_l = bpy.context.active_object
    fill_l.data.energy = 110
    fill_l.data.size = 3.5
    fill_l.data.color = (0.45, 0.68, 1.0)
    fill_l.rotation_euler = Euler((math.radians(78), 0, math.radians(-18)), "XYZ")

    # Resolve Japanese font cleanly for 3D sculptural text
    font_path = _find_japanese_font()
    jp_font = bpy.data.fonts.load(font_path) if font_path else None
    print(f"[BLENDER_SCENE] Loaded Japanese font: {font_path}", flush=True)

    # Build Act-linked 3D Japanese Sculptures + Pitch Pillars + Floating 3D Glass Cards
    for act in acts:
        sf = int(act["start_frame"])
        ef = int(act["end_frame"])
        mid = (sf + ef) // 2
        accent_rgba = _hex_to_rgba(str(act.get("accent_hex") or "#38BDF8"))

        # Animate rim light accent tint per act
        rim_l.data.color = accent_rgba[:3]
        rim_l.data.keyframe_insert(data_path="color", frame=sf)

        # 3D Extruded Japanese Word Sculpture
        word = str(act["word_jp"])
        bpy.ops.object.text_add(location=(-1.45, -0.05, 1.28), rotation=(math.radians(90), 0, math.radians(10)))
        txt_obj = bpy.context.active_object
        txt_obj.data.body = word
        if jp_font:
            txt_obj.data.font = jp_font
        txt_obj.data.align_x = "CENTER"
        txt_obj.data.align_y = "CENTER"
        txt_obj.data.size = 1.25 if len(word) <= 2 else (0.92 if len(word) <= 4 else 0.72)
        txt_obj.data.extrude = 0.095
        txt_obj.data.bevel_depth = 0.015
        txt_obj.data.bevel_resolution = 3

        sculpture_mat = _make_principled_mat(
            f"SculptMat_{act['act_index']}",
            (0.95, 0.85, 0.68, 1.0),
            metallic=0.78,
            roughness=0.22,
            emission_col=accent_rgba,
            emission_str=0.28,
            disable_mis=True,
        )
        txt_obj.data.materials.append(sculpture_mat)

        # Crisp step-in & float animation
        _keyframe_act_visibility(txt_obj, sf, ef, total_frames)
        txt_obj.scale = (0.001, 0.001, 0.001)
        txt_obj.keyframe_insert(data_path="scale", frame=max(1, sf - 1))
        txt_obj.scale = (1.0, 1.0, 1.0)
        txt_obj.keyframe_insert(data_path="scale", frame=min(ef, sf + 8))
        txt_obj.rotation_euler = Euler((math.radians(90), 0, math.radians(14)), "XYZ")
        txt_obj.keyframe_insert(data_path="rotation_euler", frame=sf)
        txt_obj.rotation_euler = Euler((math.radians(90), 0, math.radians(-8)), "XYZ")
        txt_obj.keyframe_insert(data_path="rotation_euler", frame=ef)
        txt_obj.scale = (1.0, 1.0, 1.0)
        txt_obj.keyframe_insert(data_path="scale", frame=ef)
        txt_obj.scale = (0.001, 0.001, 0.001)
        if ef < total_frames:
            txt_obj.keyframe_insert(data_path="scale", frame=ef + 1)

        # 3D Pitch Accent glowing pillars under the sculpture
        steps = [s.strip().upper() for s in str(act.get("pitch") or "L-H").split("-") if s.strip()]
        n_st = len(steps)
        pillar_hi_mat = _make_principled_mat(
            f"PillarHi_{act['act_index']}", accent_rgba, metallic=0.2, roughness=0.2,
            emission_col=accent_rgba, emission_str=2.6, disable_mis=True,
        )
        pillar_lo_mat = _make_principled_mat(f"PillarLo_{act['act_index']}", (0.18, 0.25, 0.38, 1.0), metallic=0.3, roughness=0.35)
        for pi, st in enumerate(steps):
            px = -1.45 + (pi - (n_st - 1) / 2.0) * 0.28
            h_val = 0.56 if st == "H" else 0.20
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(px, -0.05, 0.16 + h_val / 2.0))
            pil = bpy.context.active_object
            pil.data.materials.append(pillar_hi_mat if st == "H" else pillar_lo_mat)
            _keyframe_act_visibility(pil, sf, ef, total_frames)
            pil.scale = (0.001, 0.001, 0.001)
            pil.keyframe_insert(data_path="scale", frame=max(1, sf - 1))
            pil.scale = (0.14, 0.14, h_val)
            pil.keyframe_insert(data_path="scale", frame=min(ef, sf + 6))
            pil.keyframe_insert(data_path="scale", frame=ef)
            if ef < total_frames:
                pil.scale = (0.001, 0.001, 0.001)
                pil.keyframe_insert(data_path="scale", frame=ef + 1)

        # Floating 3D Beveled Glass Card Rig (parent Empty avoids Z-fighting)
        rig = bpy.data.objects.new(f"CardRig_{act['act_index']}", None)
        scene.collection.objects.link(rig)
        rig.location = (1.42, -0.05, 1.45)
        rig.rotation_euler = Euler((0, 0, math.radians(-16)), "XYZ")

        png_full = str((base_dir / act["card_png"]).resolve())
        bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, -0.032, 0.0), rotation=(math.radians(90), 0, 0))
        card_pl = bpy.context.active_object
        card_pl.parent = rig
        card_pl.data.materials.append(_make_card_texture_mat(f"CardTex_{act['act_index']}", png_full))

        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
        frame_bg = bpy.context.active_object
        frame_bg.parent = rig
        frame_bg.data.materials.append(_make_principled_mat(f"FrameRim_{act['act_index']}", (0.04, 0.07, 0.13, 1.0), metallic=0.85, roughness=0.25))

        for obj, tgt_s in ((card_pl, (2.25, 2.46, 1.0)), (frame_bg, (2.34, 0.04, 2.55))):
            _keyframe_act_visibility(obj, sf, ef, total_frames)
            obj.scale = (0.001, 0.001, 0.001)
            obj.keyframe_insert(data_path="scale", frame=max(1, sf - 1))
            obj.scale = tgt_s
            obj.keyframe_insert(data_path="scale", frame=min(ef, sf + 7))
            obj.keyframe_insert(data_path="scale", frame=ef)
            if ef < total_frames:
                obj.scale = (0.001, 0.001, 0.001)
                obj.keyframe_insert(data_path="scale", frame=ef + 1)

    # Smooth Cinematic Studio Camera
    bpy.ops.object.camera_add(location=(-0.35, -5.65, 1.62), rotation=(math.radians(85), 0, 0))
    cam = bpy.context.active_object
    cam.data.lens = 42
    scene.camera = cam

    cam.keyframe_insert(data_path="location", frame=1)
    cam.location = (0.28, -5.35, 1.54)
    cam.rotation_euler = Euler((math.radians(86), 0, math.radians(3)), "XYZ")
    cam.keyframe_insert(data_path="location", frame=total_frames // 2)
    cam.keyframe_insert(data_path="rotation_euler", frame=total_frames // 2)
    cam.location = (-0.18, -5.50, 1.68)
    cam.rotation_euler = Euler((math.radians(84), 0, math.radians(-2)), "XYZ")
    cam.keyframe_insert(data_path="location", frame=total_frames)
    cam.keyframe_insert(data_path="rotation_euler", frame=total_frames)

    # Render assigned shard frame window cleanly
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    sf_render = max(1, int(args.start_frame))
    ef_render = total_frames if int(args.end_frame) <= 0 else min(total_frames, int(args.end_frame))
    scene.frame_start = sf_render
    scene.frame_end = ef_render
    scene.render.filepath = str(out_dir / "frame_")
    print(f"[BLENDER_RENDER] Cycles CPU OIDN samples={samples} res={width}x{height} frames={sf_render}..{ef_render}", flush=True)
    bpy.ops.render.render(animation=True)
    print(f"BLENDER_SHARD_RENDER_DONE: frames={sf_render}..{ef_render}", flush=True)


if __name__ == "__main__":
    _build_and_render()
