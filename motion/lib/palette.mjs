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

export function drawBackground(ctx, W, H, palette) {
  ctx.fillStyle = palette.background;
  ctx.fillRect(0, 0, W, H);
  // Subtle vignette for production feel.
  const g = ctx.createRadialGradient(W / 2, H / 2, H * 0.2, W / 2, H / 2, H * 0.9);
  g.addColorStop(0, "rgba(255,255,255,0.03)");
  g.addColorStop(1, "rgba(0,0,0,0.25)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
}

/** Number easing: interpolate from a to b with eased t, optional grouping. */
export function lerpNumber(a, b, t, { group = true } = {}) {
  const v = a + (b - a) * easeOutCubic(t);
  const rounded = Math.round(v);
  return group ? rounded.toLocaleString("en-US") : String(rounded);
}
