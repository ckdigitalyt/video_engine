"""noise_cancel — deterministic plates + diagram cards + bed/SFX.

ANC story: earcup cutaway, wave inversion, superposition, frequency band,
feedback loop, silence payoff. All art Pillow-drawn via _v6_cardlib
(no image-model calls, no network), parchment family per the shared visual
bible. V7 chrome policy: NO baked title bars; cards carry only subtle
footer section markers.
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _v6_cardlib import (ASSETS, CREAM, INK, NAVY, NAVY_D, PARCH, PARCH_L,
                         RUST, W, arrow, bgrid, footer_band, finish_plate,
                         inter, label, parchment, register_diagram,
                         save_plate, synth_bed, synth_sfx, write_manifest)
from PIL import Image, ImageDraw

from engine import bible as B

STORY = Path(__file__).resolve().parent
bible = B.load_bible(STORY)


# ------------------------------------------------------------ helpers ---

def rounded(d, box, r, **kw):
    d.rounded_rectangle(box, radius=r, **kw)


GREY_NAVY = (70, 74, 84)   # desaturated chrome: reads as ink wash, drops out
# of the hue histogram (cardlib convention) so the saturated rust/navy
# accents own the palette match.


def glow(d, cx, cy, r, col, layers=6):
    for i in range(layers, 0, -1):
        rr = r * i / layers
        a = int(70 / layers * (layers - i + 1))
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=col + (a,))


def sine(d, x0, x1, y0, amp, periods, col, width=7, flip=False, phase=0.0,
         alpha=235):
    pts = []
    n = 96
    for u in range(n + 1):
        x = x0 + (x1 - x0) * u / n
        s = math.sin(2 * math.pi * periods * u / n + phase)
        if flip:
            s = -s
        pts.append((x, y0 - amp * s))
    d.line(pts, fill=col + (alpha,), width=width, joint="curve")


def wave_arcs(d, cx, cy, r0, n, col, w=5, a0=215, flip=False):
    """Concentric wave arcs radiating from (cx, cy). flip=True opens left."""
    for k in range(n):
        r = r0 + k * 46
        a = max(40, a0 - k * 32)
        if flip:
            d.arc((cx - r, cy - r, cx + r, cy + r), start=118, end=242,
                  fill=col + (a,), width=w)
        else:
            d.arc((cx - r, cy - r, cx + r, cy + r), start=-62, end=62,
                  fill=col + (a,), width=w)


def earcup(d, x0, y0, x1, y1, driver=True):
    """Shell + cavity + driver disc + seal pad. Returns (driver_cx, driver_cy)."""
    rounded(d, (x0, y0, x1, y1), 110, fill=GREY_NAVY + (255,),
            outline=INK + (255,), width=6)
    rounded(d, (x0 + 42, y0 + 42, x1 - 42, y1 - 42), 84, fill=PARCH + (240,))
    dcx = x0 + 96
    dcy = (y0 + y1) // 2
    if driver:
        d.ellipse((dcx - 34, dcy - 130, dcx + 34, dcy + 130),
                  fill=RUST + (235,), outline=INK + (255,), width=4)
        d.ellipse((dcx - 14, dcy - 92, dcx + 14, dcy + 92), fill=CREAM + (235,))
    # ear seal on the canal side (right)
    rounded(d, (x1 - 54, (y0 + y1) // 2 - 120, x1 - 18, (y0 + y1) // 2 + 120),
            26, fill=NAVY + (200,), outline=INK + (180,), width=3)
    return dcx, dcy


# ---------------------------------------------------------------- plates ---

def b1_anc_cutaway_hero():
    img = parchment(701)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 1060, 530, 330, RUST)   # warm wash behind the whole subject
    # incoming noise arcs from the left
    wave_arcs(d, 380, 500, 60, 5, NAVY)
    label(d, "NOISE IN", (300, 500), (90, 300))
    # earcup cutaway
    dcx, dcy = earcup(d, 760, 280, 1330, 780)
    # anti-noise arcs from the driver into the cavity (opening left)
    wave_arcs(d, dcx + 40, dcy, 54, 4, RUST, flip=True)
    # outer mic dot on the shell's left edge
    d.ellipse((726, 488, 752, 514), fill=NAVY + (255,),
              outline=INK + (255,), width=3)
    label(d, "OUTER MIC", (739, 501), (560, 640))
    label(d, "DRIVER", (dcx, dcy - 150), (900, 180))
    label(d, "EARCUP", (1100, 300), (1180, 190))
    label(d, "ANTI-NOISE", (dcx + 150, dcy + 150), (1000, 850))
    footer_band(d, "THE ERASER")
    return finish_plate(img, 702, 0.22)


def b2_wave_invert():
    img = parchment(711)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    glow(d, 1180, 555, 215, RUST)   # warm wash between the two waves
    x0, x1 = 210, 1330
    # noise wave on top, anti-noise mirrored below
    sine(d, x0, x1, 380, 92, 3.0, NAVY, width=9)
    label(d, "NOISE", (x0 + 60, 300), (90, 190))
    sine(d, x0, x1, 730, 92, 3.0, RUST, flip=True, width=9)
    label(d, "ANTI-NOISE", (x0 + 80, 820), (90, 870))
    # crest-to-trough alignment ticks (dashed verticals at crests)
    for u in (0.083, 0.417, 0.75):
        x = x0 + (x1 - x0) * u
        for k in range(9):
            yy = 470 + k * 26
            d.line(((x, yy), (x, yy + 12)), fill=INK + (150,), width=3)
    # phase-flip arrow between the two
    arrow(d, (x1 - 130, 460), (x1 - 130, 640), col=RUST, w=7, head=24)
    label(d, "PHASE FLIP", (x1 - 130, 550), (x1 - 360, 550))
    # chip block
    rounded(d, (x0 - 40, 528, x0 + 60, 592), 10, fill=NAVY + (220,),
            outline=INK + (255,), width=4)
    label(d, "CHIP", (x0 + 10, 560), (100, 560))
    footer_band(d, "MIRROR WAVE")
    return finish_plate(img, 712, 0.18)


def b3_superposition():
    img = parchment(721)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    mx = 950  # meeting point
    glow(d, mx + 210, 500, 215, RUST)   # warm wash around the resolution
    # two waves flowing toward the meeting point
    sine(d, 180, mx - 20, 400, 80, 2.2, NAVY, width=9)
    label(d, "NOISE", (330, 330), (120, 200))
    sine(d, 180, mx - 20, 600, 80, 2.2, RUST, flip=True, width=9)
    label(d, "ANTI-NOISE", (330, 680), (120, 760))
    # convergence arrows
    arrow(d, (mx - 90, 380), (mx + 40, 480), col=NAVY, w=8, head=24)
    arrow(d, (mx - 90, 620), (mx + 40, 520), col=RUST, w=8, head=24)
    d.ellipse((mx - 12, 468, mx + 12, 492), fill=INK + (255,))
    # flat sum line beyond the meeting point
    glow(d, 1160, 500, 150, CREAM)
    d.line(((mx + 20, 500), (1360, 500)), fill=CREAM + (255,), width=10)
    label(d, "SUM: SILENCE", (1170, 500), (1080, 640))
    footer_band(d, "DESTRUCTIVE INTERFERENCE")
    return finish_plate(img, 722, 0.18)


def b4_freq_band():
    img = parchment(731)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    ax0, ay0, ax1, ay1 = 230, 280, 1360, 800
    glow(d, ax0 + 300, ay1 - 320, 300, RUST)   # warm wash behind the tall bars
    d.line(((ax0, ay0), (ax0, ay1)), fill=INK + (255,), width=6)
    d.line(((ax0, ay1), (ax1, ay1)), fill=INK + (255,), width=6)
    # falling bar envelope: deep cancel at low frequency, stubs at high
    heights = [420, 360, 270, 170, 95, 50]
    bw, gap = 120, 74
    for k, hgt in enumerate(heights):
        bx = ax0 + 60 + k * (bw + gap)
        col = GREY_NAVY if k < 4 else RUST
        rounded(d, (bx, ay1 - hgt, bx + bw, ay1 - 4), 8,
                fill=col + (150 if k < 4 else 130,), outline=INK + (255,),
                width=4)
    # fade marker where cancellation weakens
    fx = ax0 + 60 + 4 * (bw + gap) - 40
    for k in range(16):
        yy = ay0 + 40 + k * 30
        d.line(((fx, yy), (fx + 26, yy)), fill=RUST + (200,), width=5)
    label(d, "ATTENUATION", (ax0, 320), (60, 230))
    label(d, "LOW RUMBLE", (ax0 + 200, ay1 - 380), (150, 180))
    label(d, "HIGH HISS", (ax0 + 60 + 4 * (bw + gap) + 40, ay1 - 120),
          (ax0 + 60 + 4 * (bw + gap) - 60, 860))
    label(d, "FREQUENCY", (1300, ay1 - 40), (1180, 860))
    footer_band(d, "WHAT SURVIVES")
    return finish_plate(img, 732, 0.18)


def b5_feedback_loop():
    img = parchment(741)
    d = ImageDraw.Draw(img, "RGBA")
    bgrid(d)
    cx, cy = 768, 520
    glow(d, cx, cy, 330, RUST)   # warm wash under the loop
    # mini earcup at center
    earcup(d, cx - 190, cy - 160, cx + 250, cy + 160)
    # loop nodes
    nodes = {"INNER MIC": (cx - 300, cy + 190), "CHIP": (cx - 330, cy - 200),
             "DRIVER": (cx + 330, cy - 170)}
    for txt, (nx, ny) in nodes.items():
        d.ellipse((nx - 26, ny - 26, nx + 26, ny + 26), fill=NAVY + (230,),
                  outline=INK + (255,), width=4)
        label(d, txt, (nx, ny),
              (nx - 120, ny - 120) if ny < cy else (nx - 160, ny + 60))
    # circular correction arrows (mic -> chip -> driver -> cup)
    d.arc((nodes["CHIP"][0] + 20, cy - 220, nodes["DRIVER"][0] - 20, cy + 240),
          start=180, end=270, fill=RUST + (220,), width=7)
    d.arc((nodes["INNER MIC"][0] + 20, cy - 240, nodes["DRIVER"][0] - 20, cy + 220),
          start=270, end=360, fill=RUST + (220,), width=7)
    d.arc((nodes["CHIP"][0] + 10, cy - 180, nodes["INNER MIC"][0] + 180, cy + 240),
          start=90, end=180, fill=RUST + (220,), width=7)
    arrow(d, (cx - 150, cy + 250), (cx - 60, cy + 250), col=RUST, w=7, head=22)
    label(d, "RESIDUAL", (cx + 60, cy + 300), (cx + 130, cy + 330))
    footer_band(d, "ALWAYS CORRECTING")
    return finish_plate(img, 742, 0.18)


def b6_silence_payoff():
    img = parchment(751)
    tint = Image.new("RGBA", (W_, H_), (212, 148, 84, 34))  # dusk warmth
    img = Image.alpha_composite(img, tint)
    d = ImageDraw.Draw(img, "RGBA")
    glow(d, 760, 950, 640, RUST)   # phone-b6 style dusk glows
    glow(d, 700, 930, 440, RUST)
    dcx, dcy = earcup(d, 620, 300, 1190, 800)
    glow(d, 900, 550, 240, CREAM)
    # flat silence line through the whole frame
    d.line(((140, 540), (1400, 540)), fill=CREAM + (255,), width=10)
    label(d, "NOISE MINUS NOISE", (760, 540), (520, 870))
    footer_band(d, "MADE OF SOUND")
    return finish_plate(img, 752, 0.24)


from _v6_cardlib import H as H_, W as W_  # canvas size for the tint layer


def main():
    ASSETS.mkdir(exist_ok=True)
    plates = {
        "B1_anc_cutaway_hero": b1_anc_cutaway_hero(),
        "B2_wave_invert": b2_wave_invert(),
        "B3_superposition": b3_superposition(),
        "B4_freq_band": b4_freq_band(),
        "B5_feedback_loop": b5_feedback_loop(),
        "B6_silence_payoff": b6_silence_payoff(),
    }
    scores = []
    for name, img in plates.items():
        scores.append(save_plate(img, name, bible))
    d_scores = []
    for name in ("B2_wave_invert", "B3_superposition", "B4_freq_band",
                 "B5_feedback_loop"):
        ds, _ = register_diagram(name, bible)
        d_scores.append(ds)
    write_manifest([("B2_wave_invert", "diagram"),
                    ("B3_superposition", "diagram"),
                    ("B4_freq_band", "diagram"),
                    ("B5_feedback_loop", "diagram")])
    STORY.joinpath("audio").mkdir(exist_ok=True)
    synth_bed(STORY / "audio" / "bed_ambient.wav", seed=91, base_hz=110.0,
              dur=60.0)
    synth_sfx(STORY / "audio" / "sfx_reveal.wav", seed=89, kind="swell",
              dur=1.8)
    low = [n for n, s in zip(plates, scores) if s < 0.55]
    if low:
        print(f"LOW CONTINUITY: {low}")
        raise SystemExit(1)
    print(f"cards ok: {len(plates)} plates, diagram min {min(d_scores):.2f}")


if __name__ == "__main__":
    main()
