// lib/events.mjs — §4/§16 micro-event layer for the node-canvas renderers.
//
// Renders a shot's micro-event cues as REAL discrete perceptual events on
// top of the template/scene draw:
//   pre-draw  (camera): zoom_kick scale + shake jitter transform
//   post-draw (frame):  flash / darken / cut grade overlays, procedural
//                       silhouette + particle overlays (flock, run figure,
//                       rain, dust, embers)
// Cues contract (engine.v4.motion_toolkit.canvas_event_cues):
//   {start, end, type, amp, kind?, blend?, seed?} — frame indices.
// Fully deterministic given the cue list.

export function activeCues(cues, frame) {
  return (cues || []).filter((c) => frame >= c.start && frame <= c.end);
}

/** Camera-space transform for the frame (apply before template draw). */
export function cameraFor(cues, frame, W, H) {
  let scale = 1, dx = 0, dy = 0;
  for (const c of activeCues(cues, frame)) {
    if (c.type === "zoom_kick") {
      const span = Math.max(1, c.end - c.start);
      const p = (frame - c.start) / span;
      const tri = 1 - Math.abs(2 * p - 1); // 0→1→0
      scale *= 1 + (c.amp || 0.06) * tri;
    } else if (c.type === "shake") {
      const span = Math.max(1, c.end - c.start);
      const decay = 1 - (frame - c.start) / span;
      const s = c.seed ?? 7;
      dx += (c.amp || 0.02) * W * decay * Math.sin(frame * 9.3 + s);
      dy += (c.amp || 0.02) * H * 0.8 * decay * Math.cos(frame * 7.7 + s);
    }
  }
  return { scale, dx, dy };
}

/** Full-frame overlays (apply after template draw). Returns true if the
 * frame was visibly altered (grade overlays count even without cues). */
export function drawEventOverlays(ctx, W, H, cues, frame, fps) {
  let altered = false;
  for (const c of activeCues(cues, frame)) {
    const span = Math.max(1, c.end - c.start);
    const p = (frame - c.start) / span;
    const tri = 1 - Math.abs(2 * p - 1); // fast in, fast out
    if (c.type === "flash") {
      ctx.save();
      ctx.globalAlpha = Math.min(0.85, (c.amp || 0.5) * tri);
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, W, H);
      ctx.restore();
      altered = true;
    } else if (c.type === "darken") {
      ctx.save();
      ctx.globalAlpha = Math.min(0.6, (c.amp || 0.35) * tri);
      ctx.fillStyle = "#000000";
      ctx.fillRect(0, 0, W, H);
      ctx.restore();
      altered = true;
    } else if (c.type === "cut") {
      // hard internal cut-to: two-frame full grade flip
      ctx.save();
      ctx.globalAlpha = Math.min(0.7, (c.amp || 0.45));
      ctx.fillStyle = p < 0.5 ? "#1a2436" : "#e8d9b8";
      ctx.fillRect(0, 0, W, H);
      ctx.restore();
      altered = true;
    } else if (c.type === "overlay") {
      drawOverlay(ctx, W, H, c, frame - c.start, span);
      altered = true;
    }
  }
  return altered;
}

/** Continuous ambient life (§3 anti-hold): a slow two-sine exposure
 * breathing keeps frame-pair deltas just above the static threshold
 * between events (~0.7+ luma/frame on dark plates) without reading as
 * flicker (±11 luma swing over ~3 s). Deterministic. */
export function drawAmbientBreath(ctx, W, H, frame) {
  const a = 0.045 * (0.5 - 0.5 * Math.cos(2 * Math.PI * frame / 90)
    + 0.3 * Math.sin(2 * Math.PI * frame / 37));
  const alpha = Math.abs(a) * 0.5;
  ctx.save();
  ctx.globalAlpha = Math.min(0.06, alpha);
  ctx.fillStyle = a >= 0 ? "#ffffff" : "#000000";
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}

// ── procedural overlay silhouettes / particles (JS, deterministic) ──

function hash01(s) {
  let h = 2166136261 >>> 0;
  const str = String(s);
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return (h % 100000) / 100000;
}

function drawBird(ctx, x, y, s, flap, color) {
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(2, s * 0.28);
  ctx.beginPath();
  ctx.moveTo(x - s, y + flap * s * 0.6);
  ctx.quadraticCurveTo(x, y - flap * s * 0.8, x + s, y + flap * s * 0.6);
  ctx.stroke();
}

function drawFigure(ctx, x, y, s) {
  ctx.fillStyle = "rgba(10,10,14,0.85)";
  ctx.beginPath();
  ctx.ellipse(x, y - s * 0.9, s * 1.1, s * 0.45, 0, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillRect(x - s * 0.9, y - s * 0.9, s * 0.16, s * 0.9);
  ctx.fillRect(x - s * 0.3, y - s * 0.9, s * 0.16, s * 0.9);
  ctx.fillRect(x + s * 0.3, y - s * 0.9, s * 0.16, s * 0.9);
  ctx.fillRect(x + s * 0.8, y - s * 1.05, s * 0.5, s * 0.3); // head
}

function drawOverlay(ctx, W, H, cue, f, span) {
  const kind = cue.kind || "dust";
  const seed = cue.seed ?? 11;
  const prog = span > 0 ? f / span : 0;
  if (kind === "flock") {
    const n = 6 + Math.floor(hash01(seed) * 5);
    for (let i = 0; i < n; i++) {
      const lag = hash01(seed + i) * 0.25;
      const p = prog - lag;
      if (p < 0 || p > 1.15) continue;
      const x = (-0.1 + p * 1.2) * W;
      const y = H * (0.22 + 0.3 * hash01(seed + 40 + i)
        + 0.05 * Math.sin(p * 9 + i));
      drawBird(ctx, x, y, 8 + 6 * hash01(seed + 80 + i),
        Math.sin(p * 20 + i), "rgba(12,12,18,0.85)");
    }
  } else if (kind === "run" || kind === "walk") {
    const p = Math.min(1.1, prog * 1.05);
    if (p >= 0) {
      const x = (-0.12 + p * 1.25) * W;
      const bob = Math.abs(Math.sin(prog * 16)) * H * 0.012;
      drawFigure(ctx, x, H * 0.86 - bob, H * 0.09);
    }
  } else if (kind === "rain" || kind === "dust" || kind === "embers") {
    const n = kind === "rain" ? 130 : 60;
    ctx.save();
    for (let i = 0; i < n; i++) {
      const rx = hash01(seed + i * 3), ry = hash01(seed + i * 7 + 1);
      const speed = kind === "rain" ? 0.9 : 0.35;
      let x = rx * W;
      let y = ((ry + speed * prog * (0.6 + 0.8 * hash01(i + 2))) % 1.2 - 0.1) * H;
      if (kind === "embers") y = ((ry - speed * prog * 0.8) % 1 + 1) % 1 * H;
      const alpha = 0.5 * Math.sin(Math.min(1, prog) * Math.PI) + 0.08;
      if (kind === "rain") {
        ctx.strokeStyle = `rgba(200,220,255,${alpha})`;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x - H * 0.015, y + H * 0.05);
        ctx.stroke();
      } else {
        ctx.fillStyle = kind === "embers"
          ? `rgba(255,150,60,${alpha})` : `rgba(210,190,160,${alpha})`;
        const s = 2 + 2 * hash01(i + 5);
        ctx.fillRect(x, y, s, s);
      }
    }
    ctx.restore();
  }
}
