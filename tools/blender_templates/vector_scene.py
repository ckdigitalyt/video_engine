"""
Vector beat renderer (v12) — Kurzgesagt-style flat-vector ANIMATED clips,
Blender 4.0.2 headless + Workbench FLAT + transparent PNGs (ffmpeg
composites onto the channel navy).  One parameterized script; the
template is selected via VC_TEMPLATE.

Fixes the two biggest v11 failures: the sleep episode shipped with
`manim: 0` and ZERO vector animation (19 cached stills + 1 AI image).

Environment:
  VC_TEMPLATE   orbit | figure_walk | pulse | bars | clock | waves
  VC_FRAMES     total frames (30 fps default)
  VC_FPS, VC_W, VC_H, VC_OUT (frame dir), VC_BG "r,g,b" (0..1),
  VC_PAL_*      optional per-template palette overrides (hex or "r,g,b")

Blender 4.0 gotchas handled: workbench settings live on
scene.display.shading; diffuse_color is LINEAR (sRGB→linear for palette
accuracy); camera looks along +Y (rot 90° X); shapes live in the XZ
plane rotated 90° X to face the camera; default objects cleared first.
"""
import bpy
import math
import os
import sys

TPL = os.environ.get("VC_TEMPLATE", "orbit")
FRAMES = int(os.environ.get("VC_FRAMES", "240"))
FPS = int(os.environ.get("VC_FPS", "30"))
W = int(os.environ.get("VC_W", "1920"))
H = int(os.environ.get("VC_H", "1080"))
OUT = os.environ.get("VC_OUT", "/tmp/vecframes")
BG = tuple(float(x) for x in os.environ.get("VC_BG", "0.067,0.071,0.125").split(","))

# ── palette (channel flat-vector; hex → linear for Workbench) ──────────
def _lin(hexv):
    hexv = hexv.lstrip("#")
    return tuple((int(hexv[i:i + 2], 16) / 255.0) ** 2.2 for i in (0, 2, 4))

PAL = {
    "cyan": _lin(os.environ.get("VC_PAL_CYAN", "#22D3EE")),
    "orange": _lin(os.environ.get("VC_PAL_ORANGE", "#F47F3F")),
    "lime": _lin(os.environ.get("VC_PAL_LIME", "#A3E635")),
    "skin": _lin(os.environ.get("VC_PAL_SKIN", "#F0C4A8")),
    "red": _lin(os.environ.get("VC_PAL_RED", "#F87171")),
    "white": _lin(os.environ.get("VC_PAL_WHITE", "#F1F5F9")),
    "dim": _lin(os.environ.get("VC_PAL_DIM", "#5B6478")),
}

# ── clear default scene ─────────────────────────────────────────────────
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
for mesh in list(bpy.data.meshes):
    bpy.data.meshes.remove(mesh)

scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = W
scene.render.resolution_y = H
scene.render.fps = FPS
scene.frame_start = 1
scene.frame_end = FRAMES
scene.render.image_settings.file_format = "PNG"
scene.render.film_transparent = True
scene.view_settings.view_transform = "Standard"
scene.display.shading.light = "FLAT"
scene.display.shading.color_type = "MATERIAL"

cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
cam.location = (0, -12, 0)
cam.rotation_euler = (1.5707963, 0, 0)
scene.collection.objects.link(cam)
scene.camera = cam


def flat_mat(name, rgb):
    m = bpy.data.materials.new(name)
    m.use_nodes = False
    m.diffuse_color = (*rgb, 1.0)
    return m


def disc(name, radius, mat, verts=64):
    import bmesh
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    pts = [(radius * math.cos(2 * math.pi * i / verts),
            radius * math.sin(2 * math.pi * i / verts), 0) for i in range(verts)]
    vs = [bm.verts.new(p) for p in pts]
    bm.faces.new(vs)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    obj.rotation_euler = (1.5707963, 0, 0)
    scene.collection.objects.link(obj)
    return obj


def ring(name, radius, mat, thickness=0.05, verts=64):
    import bmesh
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    outer = [(radius * math.cos(2 * math.pi * i / verts),
              radius * math.sin(2 * math.pi * i / verts), 0) for i in range(verts)]
    inner = [((radius - thickness) * math.cos(2 * math.pi * i / verts),
              (radius - thickness) * math.sin(2 * math.pi * i / verts), 0) for i in range(verts)]
    ov = [bm.verts.new(p) for p in outer]
    iv = [bm.verts.new(p) for p in inner]
    for i in range(verts):
        bm.faces.new([ov[i], ov[(i + 1) % verts], iv[(i + 1) % verts], iv[i]])
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    obj.rotation_euler = (1.5707963, 0, 0)
    scene.collection.objects.link(obj)
    return obj


def rect(name, w, h, mat, z=0.0):
    """Flat rounded-ish rectangle in the XZ plane (screen plane)."""
    import bmesh
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    r = min(w, h) * 0.18
    pts = []
    for a in range(0, 360, 5):
        x = (w / 2 - r) * math.cos(math.radians(a))
        zz = (h / 2 - r) * math.sin(math.radians(a))
        rr = r if (x >= -w / 2 + r and x <= w / 2 - r and
                   zz >= -h / 2 + r and zz <= h / 2 - r) else 0
        if rr == 0:
            x = max(-w / 2 + r, min(w / 2 - r, x))
            zz = max(-h / 2 + r, min(h / 2 - r, zz))
        pts.append((x, zz, z))
    vs = [bm.verts.new(p) for p in pts]
    bm.faces.new(vs)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(mat)
    obj.rotation_euler = (1.5707963, 0, 0)
    scene.collection.objects.link(obj)
    return obj


def key_scale(obj, start_f, end_f, s0=0.001, s1=1.0):
    obj.scale = (s0, s0, s0)
    obj.keyframe_insert(data_path="scale", frame=start_f)
    obj.scale = (s1, s1, s1)
    obj.keyframe_insert(data_path="scale", frame=end_f)


def key_loc(obj, f, xyz):
    obj.location = xyz
    obj.keyframe_insert(data_path="location", frame=f)


# ═══════════════════════════════════════════════════════════════════════ #
# Template builders
# ═══════════════════════════════════════════════════════════════════════ #

def build_orbit():
    m_cyan = flat_mat("m_cyan", PAL["cyan"])
    m_lime = flat_mat("m_lime", PAL["lime"])
    m_dim = flat_mat("m_dim", PAL["dim"])
    m_white = flat_mat("m_white", PAL["white"])
    planet = disc("planet", 2.0, m_cyan)
    ring_orb = ring("orbit", 3.4, m_dim, thickness=0.04)
    band = disc("band", 2.02, m_dim)
    band.scale = (1.0, 0.09, 1.0)
    band.location = (0, 0, 0.35)
    bar = disc("bar", 0.5, m_white)
    bar.scale = (10.0, 0.06, 1.0)
    bar.location = (0, 0, -3.8)
    for obj in (planet, ring_orb, bar, band):
        obj.scale = (0.001, 0.001, 0.001)
        obj.keyframe_insert(data_path="scale", frame=1)
    for i, obj in enumerate((planet, ring_orb, bar)):
        key_scale(obj, 8 + i * 8, 26 + i * 8)
    key_scale(band, 30, 44)
    moon = disc("moon", 0.32, m_lime)
    for f in range(1, FRAMES + 1):
        a = 2 * math.pi * (f - 1) / max(1, FRAMES - 1)
        moon.location = (3.4 * math.cos(a), 0, 3.4 * math.sin(a))
        moon.keyframe_insert(data_path="location", frame=f)
    key_loc(cam, 1, (0, -12, 0))
    key_loc(cam, FRAMES, (0, -8.5, 0.4))


def build_figure_walk():
    """Kurzgesagt human figure walking in place (circle head, rounded
    torso, pivoted limbs) — the classic 'tiny human' beat."""
    m_skin = flat_mat("m_skin", PAL["skin"])
    m_shirt = flat_mat("m_shirt", PAL["orange"])
    m_pants = flat_mat("m_pants", PAL["dim"])
    m_shoe = flat_mat("m_shoe", PAL["white"])
    head = disc("head", 0.42, m_skin)
    head.location = (0, 0, 2.05)
    torso = rect("torso", 1.5, 1.55, m_shirt, z=0.7)
    # limbs as thin rotated discs (capsule look)
    def limb(name, mat, length, px=0.0, pz=0.0, angle=0.0):
        l = disc(name, length, mat)
        l.scale = (0.16, 1.0, 0.16)
        l.rotation_euler = (1.5707963, 0, angle)
        l.location = (px, 0, pz)
        return l
    arm_l = limb("arm_l", m_shirt, 0.95, -0.62, 1.35, -0.5)
    arm_r = limb("arm_r", m_shirt, 0.95, 0.62, 1.35, 0.5)
    leg_l = limb("leg_l", m_pants, 1.1, -0.28, 0.05, -0.35)
    leg_r = limb("leg_r", m_pants, 1.1, 0.28, 0.05, 0.35)
    for obj, f0 in ((head, 1), (torso, 1), (arm_l, 1), (arm_r, 1),
                    (leg_l, 1), (leg_r, 1)):
        key_scale(obj, f0, f0 + 18)
    # walk cycle: legs ±29°, arms counter-swing ±20°, body bob
    cycle = 30
    for f in range(1, FRAMES + 1):
        t = (f - 1) / cycle * 2 * math.pi
        swing = math.sin(t)
        leg_l.rotation_euler = (1.5707963, 0, -0.35 + 0.58 * swing * 0.5)
        leg_l.keyframe_insert(data_path="rotation_euler", frame=f)
        leg_r.rotation_euler = (1.5707963, 0, 0.35 - 0.58 * swing * 0.5)
        leg_r.keyframe_insert(data_path="rotation_euler", frame=f)
        arm_l.rotation_euler = (1.5707963, 0, -0.5 - 0.4 * swing * 0.5)
        arm_l.keyframe_insert(data_path="rotation_euler", frame=f)
        arm_r.rotation_euler = (1.5707963, 0, 0.5 + 0.4 * swing * 0.5)
        arm_r.keyframe_insert(data_path="rotation_euler", frame=f)
        bob = 0.05 * math.sin(2 * t)
        torso.location = (0, 0, 0.7 + bob)
        torso.keyframe_insert(data_path="location", frame=f)
        head.location = (0, 0, 2.05 + bob)
        head.keyframe_insert(data_path="location", frame=f)
    shadow = disc("shadow", 1.1, flat_mat("m_shadow", (0.02, 0.02, 0.05)))
    shadow.location = (0, 0, -1.6)
    key_loc(cam, 1, (0, -10, 0))
    key_loc(cam, FRAMES, (0, -10, 0))


def build_pulse():
    m_cyan = flat_mat("m_cyan", PAL["cyan"])
    m_lime = flat_mat("m_lime", PAL["lime"])
    m_orange = flat_mat("m_orange", PAL["orange"])
    m_red = flat_mat("m_red", PAL["red"])
    rings = [ring(f"ring{i}", 1.0 + 0.7 * i, m, thickness=0.07)
             for i, m in enumerate((m_cyan, m_lime, m_orange, m_red))]
    for i, r in enumerate(rings):
        key_scale(r, 1, 20, s0=0.2, s1=1.0)
    core = disc("core", 0.55, flat_mat("m_core", PAL["white"]))
    key_scale(core, 1, 15)
    # heartbeat pulse: rings expand and fade via scale pulses
    for f in range(1, FRAMES + 1):
        t = (f - 1) / FPS
        for i, r in enumerate(rings):
            ph = (t * 1.6 + i * 0.35) % 1.0
            s = 0.6 + 0.9 * ph
            r.scale = (s, s, s)
            r.keyframe_insert(data_path="scale", frame=f)
        cs = 1.0 + 0.25 * math.sin(t * 2 * math.pi * 1.6)
        core.scale = (cs, cs, cs)
        core.keyframe_insert(data_path="scale", frame=f)
    key_loc(cam, 1, (0, -9, 0))
    key_loc(cam, FRAMES, (0, -9, 0))


def build_bars():
    """Growing bar chart — data beats."""
    colors = [PAL["red"], PAL["lime"], PAL["cyan"], PAL["orange"], PAL["white"]]
    bars = []
    for i in range(5):
        m = flat_mat(f"m_bar{i}", colors[i % len(colors)])
        b = rect(f"bar{i}", 1.4, 0.001, m, z=-2.0)
        b.location = ((i - 2) * 2.0, 0, -2.0)
        bars.append(b)
    targets = [3.4, 5.2, 4.3, 6.1, 2.8]
    for i, b in enumerate(bars):
        for f in range(1, FRAMES + 1):
            t = (f - 1) / FPS
            prog = min(1.0, t / (2.2 + i * 0.5))
            hgt = 0.001 + (targets[i] - 0.001) * (1 - (1 - prog) ** 2)
            b.scale = (1.0, 1.0, hgt / 0.001)  # scale Z (after rot, screen Y)
            b.keyframe_insert(data_path="scale", frame=f)
    baseline = rect("base", 11.0, 0.12, flat_mat("m_base", PAL["dim"]), z=-2.0)
    key_scale(baseline, 1, 12, s0=0.001, s1=1.0)
    key_loc(cam, 1, (0, -8.5, -0.5))
    key_loc(cam, FRAMES, (0, -8.5, -0.5))


def build_clock():
    """Analog clock sweeping to 7 — time/sleep beats."""
    m_white = flat_mat("m_white", PAL["white"])
    m_cyan = flat_mat("m_cyan", PAL["cyan"])
    m_orange = flat_mat("m_orange", PAL["orange"])
    face = ring("face", 2.3, m_white, thickness=0.12)
    key_scale(face, 1, 18)
    ticks = []
    for k in range(12):
        a = 2 * math.pi * k / 12
        tk = disc(f"tick{k}", 0.12, m_white)
        tk.scale = (0.5, 0.5, 0.5)
        tk.location = (1.95 * math.cos(a), 0, 1.95 * math.sin(a))
        ticks.append(tk)
    hour = disc("hour", 0.10, m_cyan)
    hour.scale = (1.0, 0.09, 1.0)
    minute = disc("minute", 0.10, m_orange)
    minute.scale = (1.0, 0.06, 1.0)
    # rotate hands around center (rotation about Y after the 90° X flips to
    # screen rotation: use rotation_euler Y for in-plane spin)
    for f in range(1, FRAMES + 1):
        t = (f - 1) / max(1, FRAMES - 1)
        # minute hand: full circle; hour hand: to the 7 (210°)
        ma = -t * 2 * math.pi
        ha = -t * (2 * math.pi * 7 / 12)
        minute.rotation_euler = (1.5707963, ma, 0)
        minute.keyframe_insert(data_path="rotation_euler", frame=f)
        hour.rotation_euler = (1.5707963, ha, 0)
        hour.keyframe_insert(data_path="rotation_euler", frame=f)
    key_loc(cam, 1, (0, -9, 0))
    key_loc(cam, FRAMES, (0, -7.4, 0.3))


def build_waves():
    """Layered sine waves — brain/rhythm beats."""
    colors = [PAL["cyan"], PAL["lime"], PAL["orange"], PAL["red"]]
    rows = []
    for i, c in enumerate(colors):
        m = flat_mat(f"m_w{i}", c)
        row = []
        for j in range(24):
            b = rect(f"w{i}_{j}", 0.5, 0.16, m)
            b.location = ((j - 11.5) * 0.8, 0, (i - 1.5) * 1.6)
            row.append(b)
        rows.append(row)
    for f in range(1, FRAMES + 1):
        t = (f - 1) / FPS
        for i, row in enumerate(rows):
            for j, b in enumerate(row):
                y = 0.28 * math.sin((j / 24.0) * 2 * math.pi * 2 + t * (3 + i * 1.2))
                b.location = ((j - 11.5) * 0.8, 0, (i - 1.5) * 1.6 + y)
                b.keyframe_insert(data_path="location", frame=f)
    key_loc(cam, 1, (0, -10, 0.2))
    key_loc(cam, FRAMES, (0, -10, 0.2))


BUILDERS = {
    "orbit": build_orbit,
    "figure_walk": build_figure_walk,
    "pulse": build_pulse,
    "bars": build_bars,
    "clock": build_clock,
    "waves": build_waves,
}

if TPL not in BUILDERS:
    raise SystemExit(f"unknown template: {TPL}")
BUILDERS[TPL]()

os.makedirs(OUT, exist_ok=True)
scene.render.filepath = os.path.join(OUT, "frame_")
bpy.ops.render.render(animation=True)
print(f"VECTOR_DONE template={TPL} frames={FRAMES}")
