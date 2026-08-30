// lib/scene.mjs — scene framework: camera, parallax, characters, particles.
// Deterministic: all motion derives from frame index / local time, never
// Math.random() — particle fields are seeded LCG streams.

export const CAMERA_MOVES = new Set([
  "static", "push_in", "pull_out", "pan_left", "pan_right", "shake",
]);

/** Camera transform for progress t in [0,1]. */
export function cameraTransform(camera, t, W, H) {
  const move = String(camera?.move ?? "static");
  const dur = Number(camera?.duration ?? 0); // informational; t is normalized
  let scale = 1, dx = 0, dy = 0, rot = 0;
  const eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
  switch (move) {
    case "push_in": scale = 1 + 0.18 * eased; break;
    case "pull_out": scale = 1.18 - 0.18 * eased; break;
    case "pan_left": dx = 0.08 * W * eased; break;
    case "pan_right": dx = -0.08 * W * eased; break;
    case "shake":
      // deterministic pseudo-shake (no Math.random)
      dx = Math.sin(t * Math.PI * 24) * 10 * (1 - t);
      dy = Math.cos(t * Math.PI * 19) * 8 * (1 - t);
      rot = Math.sin(t * Math.PI * 16) * 0.006 * (1 - t);
      break;
    default: break;
  }
  return { scale, dx, dy, rot, move };
}

/** Character idle/run bob offset. */
export function characterOffset(action, t, frame) {
  switch (String(action ?? "idle")) {
    case "idle":
    case "bob":
      return { dy: Math.sin(frame * 0.09) * 6, dx: 0, rot: 0 };
    case "run": {
      return {
        dy: Math.abs(Math.sin(frame * 0.22)) * -14,
        dx: 0, // horizontal travel comes from the scene config (path)
        rot: Math.sin(frame * 0.22) * 0.02,
      };
    }
    case "none": default: return { dy: 0, dx: 0, rot: 0 };
  }
}

/** Seeded particle field (deterministic LCG per particle index). */
export function particleField(count, seed, W, H) {
  let s = seed >>> 0 || 1;
  const next = () => (s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32;
  return Array.from({ length: count }, () => ({
    x: next() * W,
    y: next() * H,
    r: 1 + next() * 3,
    speed: 0.2 + next() * 0.8,
    drift: (next() - 0.5) * 0.6,
    phase: next() * Math.PI * 2,
  }));
}

export function drawParticles(ctx, particles, t, W, H, kind) {
  ctx.save();
  for (const p of particles) {
    let x = p.x, y = p.y, alpha = 0.5;
    if (kind === "embers") {
      y = (p.y - t * H * 0.35 * p.speed) % H;
      if (y < 0) y += H;
      alpha = 0.35 + 0.3 * Math.sin(p.phase + t * 6);
      ctx.fillStyle = "rgba(255,140,60,1)";
    } else if (kind === "stars") {
      alpha = 0.3 + 0.5 * Math.abs(Math.sin(p.phase + t * 2));
      ctx.fillStyle = "rgba(230,235,255,1)";
    } else if (kind === "asteroid_field") {
      x = (p.x + t * W * 0.4 * p.speed) % (W + 40) - 20;
      ctx.fillStyle = "rgba(200,190,180,1)";
    } else { // dust
      y = (p.y + t * H * 0.12 * p.speed) % H;
      x = (p.x + Math.sin(p.phase + t * 4) * 20 * p.drift + W) % W;
      ctx.fillStyle = "rgba(220,215,200,1)";
    }
    ctx.globalAlpha = alpha * 0.6;
    ctx.beginPath();
    ctx.arc(x, y, p.r, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}

export function drawAtmosphere(ctx, W, H, t, kind) {
  ctx.save();
  if (kind === "fog") {
    const g = ctx.createLinearGradient(0, H * 0.55, 0, H);
    g.addColorStop(0, "rgba(180,190,200,0)");
    g.addColorStop(1, "rgba(180,190,200,0.28)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
    // slow drifting fog band
    const x = ((t * W * 0.05) % (W * 1.4)) - W * 0.2;
    const fg = ctx.createRadialGradient(x, H * 0.8, 50, x, H * 0.8, W * 0.35);
    fg.addColorStop(0, "rgba(200,205,215,0.18)");
    fg.addColorStop(1, "rgba(200,205,215,0)");
    ctx.fillStyle = fg;
    ctx.fillRect(0, 0, W, H);
  } else if (kind === "darkness") {
    ctx.fillStyle = `rgba(5,5,12,${0.45 * Math.min(t * 1.6, 1)})`;
    ctx.fillRect(0, 0, W, H);
  } else if (kind === "flash") {
    // brief white flash early in the shot (impact-style pattern interrupt)
    const f = Math.max(0, 1 - t * 6);
    if (f > 0) {
      ctx.fillStyle = `rgba(255,255,255,${0.85 * f})`;
      ctx.fillRect(0, 0, W, H);
    }
  }
  // subtle vignette always
  const v = ctx.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, H * 0.95);
  v.addColorStop(0, "rgba(0,0,0,0)");
  v.addColorStop(1, "rgba(0,0,0,0.28)");
  ctx.fillStyle = v;
  ctx.fillRect(0, 0, W, H);
  ctx.restore();
}
