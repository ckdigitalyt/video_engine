// lib/palette.mjs — shared drawing helpers for all templates.

export const DEFAULT_PALETTE = {
  background: "#0b0e1a",
  primary: "#e8eaf2",
  accent: "#5ac8fa",
  secondary: "#8e8ea0",
  highlight: "#ffd166",
};

export function resolvePalette(style) {
  const out = { ...DEFAULT_PALETTE };
  const pal = style?.palette || {};
  if (typeof pal === "object" && !Array.isArray(pal)) {
    for (const [k, v] of Object.entries(pal)) {
      if (typeof v === "string" && v.startsWith("#")) {
        out[k] = v;
      }
    }
  }
  // Accept a simple color list too (palette: ["#...", "#..."]).
  if (Array.isArray(pal)) {
    const keys = ["accent", "highlight", "secondary", "primary", "background"];
    pal.slice(0, 5).forEach((c, i) => { if (typeof c === "string") out[keys[i]] = c; });
  }
  return out;
}

export function font(size, weight = 600, family = "sans-serif") {
  return `${weight} ${Math.round(size)}px ${family}`;
}

export function easeOutCubic(t) {
  const c = Math.min(Math.max(t, 0), 1);
  return 1 - Math.pow(1 - c, 3);
}

export function easeInOutCubic(t) {
  const c = Math.min(Math.max(t, 0), 1);
  return c < 0.5 ? 4 * c * c * c : 1 - Math.pow(-2 * c + 2, 3) / 2;
}

export function clamp01(t) {
  return Math.min(Math.max(t, 0), 1);
}

/** Progress of an animation window [start,end] (in 0..1 of clip). */
export function window01(t, start, end) {
  if (end <= start) return t >= end ? 1 : 0;
  return clamp01((t - start) / (end - start));
}

/** Wrap long text into lines fitting maxWidth; returns array of lines. */
export function wrapText(ctx, text, maxWidth) {
  const words = String(text).split(/\s+/);
  const lines = [];
  let line = "";
  for (const w of words) {
    const test = line ? `${line} ${w}` : w;
    if (ctx.measureText(test).width > maxWidth && line) {
      lines.push(line);
      line = w;
    } else {
      line = test;
    }
  }
  if (line) lines.push(line);
  return lines;
}

export function drawBackground(ctx, W, H, palette, frame = 0,
                                 variant = 0) {
  // Per-shot stage mixing (§ de-templating): the shared dark stage used to
  // make every Motion Canvas shot dhash-identical (S12/S17 hamming 1!).
  // Each variant moves the glow, flips the gradient axis and re-weights
  // dust density so two shots never share the same coarse luminance map.
  const mix = (n) => {
    let h = 2166136261 >>> 0;
    const str = String(n);
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h;
  };
  const v = mix(variant);
  const pick = (arr, salt) => arr[(v >>> salt) % arr.length];
  const glowX = pick([0.5, 0.28, 0.72, 0.35, 0.65], 2);
  const glowY = pick([0.42, 0.35, 0.5, 0.6, 0.3], 5);
  const topLift = pick([0.10, 0.14, 0.06, 0.12, 0.08], 7);
  const glowLift = pick([0.22, 0.16, 0.28, 0.19, 0.25], 11);
  const dustN = pick([26, 18, 34, 22, 30], 13);
  const axis = v % 2;
  const top = lighten(palette.background, topLift);
  const bottom = darken(palette.background, 0.06);
  if (axis === 0) {
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, top);
    g.addColorStop(1, bottom);
    ctx.fillStyle = g;
  } else {
    const g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, top);
    g.addColorStop(1, bottom);
    ctx.fillStyle = g;
  }
  ctx.fillRect(0, 0, W, H);
  const g = ctx.createRadialGradient(W * glowX, H * glowY, H * 0.1,
                                     W * glowX, H * glowY, H * 0.95);
  g.addColorStop(0, lighten(palette.background, glowLift));
  g.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
  // Deterministic faint dust drift keeps the plate alive between events.
  for (let i = 0; i < dustN; i++) {
    const sx = frac01(i * 7 + 3 + variant) * W;
    const sy = (frac01(i * 13 + 5 + variant)
                + 0.0006 * (frame % 9000) * (0.4 + frac01(i))) % 1;
    ctx.fillStyle = `rgba(255,255,255,${0.025 + 0.03 * frac01(i * 3)})`;
    ctx.beginPath();
    ctx.arc(sx, sy * H, 1.2 + 1.6 * frac01(i * 11), 0, Math.PI * 2);
    ctx.fill();
  }
  // Subtle vignette for production feel.
  const vg = ctx.createRadialGradient(W / 2, H / 2, H * 0.2, W / 2, H / 2, H * 0.9);
  vg.addColorStop(0, "rgba(255,255,255,0.03)");
  vg.addColorStop(1, "rgba(0,0,0,0.25)");
  ctx.fillStyle = vg;
  ctx.fillRect(0, 0, W, H);
}

function frac01(n) {
  let h = 2166136261 >>> 0;
  const str = String(n);
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return (h % 100000) / 100000;
}

export function lighten(hex, amt) {
  const [r, g, b] = hexRgb(hex);
  const f = (c) => Math.min(255, Math.round(c + (255 - c) * amt));
  return `rgb(${f(r)},${f(g)},${f(b)})`;
}

export function darken(hex, amt) {
  const [r, g, b] = hexRgb(hex);
  const f = (c) => Math.max(0, Math.round(c * (1 - amt)));
  return `rgb(${f(r)},${f(g)},${f(b)})`;
}

function hexRgb(hex) {
  const h = String(hex || "#0b0e1a").replace("#", "");
  const v = h.length === 3
    ? h.split("").map((c) => parseInt(c + c, 16))
    : [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16),
       parseInt(h.slice(4, 6), 16)];
  return v.map((x) => (Number.isFinite(x) ? x : 10));
}

/** Number easing: interpolate from a to b with eased t, optional grouping. */
export function lerpNumber(a, b, t, { group = true } = {}) {
  const v = a + (b - a) * easeOutCubic(t);
  const rounded = Math.round(v);
  return group ? rounded.toLocaleString("en-US") : String(rounded);
}
