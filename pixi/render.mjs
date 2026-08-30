// render.mjs — PIXIJS headless scene renderer CLI.
//
// Usage: node render.mjs <scene.json> <out.mp4> [library_root]
//
// Scene JSON (pixi-scene-v1, directive §7):
// {
//   "background": "jungle"                     // asset name | hex color
//   "parallax_layers": [{"asset":"jungle","depth":0.4,"scale":1.1}, ...]
//   "characters": [{"type":"t_rex","position":[0.6,0.78],"action":"run",
//                   "scale":1.0,"path":[0.6,0.5]}],
//   "props_objects": [{"type":"asteroid","position":[0.3,0.25],"scale":0.6,
//                     "action":"fly_in"}],
//   "camera": {"move":"push_in","duration":2.5},
//   "particles": "dust|embers|stars|asteroid_field",
//   "atmosphere": "fog|darkness|flash",
//   "duration_sec": 3.0, "width": 1920, "height": 1080, "fps": 30
// }

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { preloadSceneAssets, LIBRARY_ROOT } from "./lib/assets.mjs";
import {
  cameraTransform,
  characterOffset,
  particleField,
  drawParticles,
  drawAtmosphere,
} from "./lib/scene.mjs";

const require = createRequire(import.meta.url);
const { createCanvas } = require("canvas");

const ASSET_ACTIONS = new Set(["static", "fly_in", "drop", "drift"]);

function flyIn(obj, t, W, H) {
  const eased = 1 - Math.pow(1 - Math.min(t * 1.4, 1), 3);
  const [px, py] = obj.position ?? [0.5, 0.4];
  if (obj.action === "fly_in") {
    return { x: (px + (1.2 - px) * (1 - eased)) * W, y: py * H };
  }
  if (obj.action === "drop") {
    return { x: px * W, y: (py - (1 - eased) * 0.5) * H };
  }
  if (obj.action === "drift") {
    return { x: (px + Math.sin(t * 3) * 0.01) * W, y: (py + t * 0.03) * H };
  }
  return { x: px * W, y: py * H };
}

async function main() {
  const [scenePath, outPath] = process.argv.slice(2);
  if (!scenePath) {
    console.error("usage: node render.mjs <scene.json> <out.mp4>");
    process.exit(2);
  }
  const scene = JSON.parse(readFileSync(scenePath, "utf-8"));
  const W = Number(scene.width ?? 1920);
  const H = Number(scene.height ?? 1080);
  const fps = Number(scene.fps ?? 30);
  const duration = Number(scene.duration_sec ?? 3.0);
  const totalFrames = Math.max(1, Math.round(duration * fps));

  const images = await preloadSceneAssets(scene);

  const canvas = createCanvas(W, H);
  const ctx = canvas.getContext("2d");
  const particles = scene.particles
    ? particleField(Number(scene.particle_count ?? 60), 42, W, H)
    : [];

  const { spawn: spawnProc } = await import("node:child_process");
  const ff = spawnProc("ffmpeg", [
    "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", `${W}x${H}`,
    "-r", String(fps), "-i", "-",
    "-an", "-c:v", "libx264", "-crf", "20", "-preset", "medium",
    "-pix_fmt", "yuv420p", outPath,
  ], { stdio: ["pipe", "ignore", "pipe"] });
  let ffErr = "";
  ff.stderr.on("data", (d) => { ffErr += d; if (ffErr.length > 8000) ffErr = ffErr.slice(-4000); });

  for (let frame = 0; frame < totalFrames; frame++) {
    const t = frame / totalFrames;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1;

    // ── background ──
    const bg = scene.background;
    if (typeof bg === "string" && bg.startsWith("#")) {
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, W, H);
    } else {
      ctx.fillStyle = "#0b0e1a";
      ctx.fillRect(0, 0, W, H);
    }

    const cam = cameraTransform(scene.camera, t, W, H);

    // Parallax layers: deeper layers move/zoom less with the camera.
    const layers = scene.background?.parallax_layers ??
      (scene.background?.asset ? [{ asset: scene.background.asset, depth: 1 }] : []);
    layers.sort((a, b) => (a.depth ?? 0.5) - (b.depth ?? 0.5));
    for (const layer of layers) {
      const img = images.get(layer.asset);
      const depth = layer.depth ?? 0.6;
      if (!img) continue;
      ctx.save();
      ctx.translate(W / 2 + cam.dx * depth, H / 2 + cam.dy * depth);
      const ls = (layer.scale ?? 1.12) * (1 + (cam.scale - 1) * depth);
      ctx.rotate(cam.rot * depth);
      ctx.scale(ls, ls);
      const s = Math.max(W / img.width, H / img.height) * 1.02;
      ctx.drawImage(img, -img.width * s / 2, -img.height * s / 2,
                    img.width * s, img.height * s);
      ctx.restore();
    }

    // Camera zoom body (characters + props share full camera strength).
    ctx.save();
    ctx.translate(W / 2 + cam.dx, H / 2 + cam.dy);
    ctx.rotate(cam.rot);
    ctx.scale(cam.scale, cam.scale);
    ctx.translate(-W / 2, -H / 2);

    // ── props_objects (asteroids, earth, icons...) ──
    for (const obj of scene.props_objects ?? []) {
      const img = images.get(obj.type);
      if (!img) continue;
      const pos = flyIn(obj, t, W, H);
      const scale = Number(obj.scale ?? 0.5) * (1 + (cam.scale - 1) * 0.5);
      const bob = characterOffset(obj.action === "drift" ? "bob" : "none", t, frame);
      ctx.save();
      ctx.translate(pos.x, pos.y + bob.dy);
      const w = img.width * scale, h = img.height * scale;
      if (obj.rotation) ctx.rotate(obj.rotation * t * Math.PI * 2);
      ctx.drawImage(img, -w / 2, -h / 2, w, h);
      ctx.restore();
    }

    // ── characters ──
    for (const ch of scene.characters ?? []) {
      const img = images.get(ch.type);
      if (!img) continue;
      const [px, py] = ch.position ?? [0.5, 0.7];
      let x = px * W;
      // run path: horizontal travel across the shot
      if (ch.path && ch.action === "run") {
        const eased = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
        x = (px + (ch.path[0] - px) * eased) * W;
      }
      const bob = characterOffset(ch.action, t, frame);
      const scale = Number(ch.scale ?? 1.0) * (1 + (cam.scale - 1) * 0.5);
      const w = img.width * scale, h = img.height * scale;
      ctx.save();
      // ground anchor: position is the character's feet
      ctx.translate(x + bob.dx, py * H + bob.dy);
      if (bob.rot) ctx.rotate(bob.rot);
      if ((ch.flip ?? false) || (ch.action === "run" && (ch.path?.[0] ?? px) < px)) {
        ctx.scale(-1, 1);
      }
      ctx.drawImage(img, -w / 2, -h, w, h);
      ctx.restore();
    }
    ctx.restore(); // camera

    if (particles.length) drawParticles(ctx, particles, t, W, H, scene.particles);
    drawAtmosphere(ctx, W, H, t, scene.atmosphere);

    const buf = canvas.toBuffer("raw");
    if (!ff.stdin.write(buf)) {
      await new Promise((res) => ff.stdin.once("drain", res));
    }
  }
  ff.stdin.end();
  await new Promise((resolve) => ff.on("close", resolve));
  if (ff.exitCode !== 0) {
    console.error(`ffmpeg failed (${ff.exitCode}): ${ffErr.slice(-1500)}`);
    process.exit(1);
  }
  console.log(JSON.stringify({
    ok: true, out: outPath, frames: totalFrames, width: W, height: H, fps,
    assets: [...images.keys()],
  }));
}

main().catch((e) => { console.error(e); process.exit(1); });
