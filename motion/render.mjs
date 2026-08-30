// render.mjs — MOTION_CANVAS headless renderer CLI.
//
// Usage: node render.mjs <scene.json> <out.mp4>
//
// Scene JSON (mc-json-v1):
// {
//   "template": "kinetic_title",       // key into templates/index.mjs
//   "props": { ...template props... }, // may include image paths (preloaded)
//   "duration_sec": 3.0,
//   "width": 1920, "height": 1080, "fps": 30,
//   "style": { "palette": {...} }      // optional style_spec_v2 palette
// }
//
// Frames are drawn with node-canvas and piped raw to ffmpeg (H.264, silent).
// Fully deterministic: same scene JSON → same bytes.

import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import { createCanvas, loadImage } from "canvas";
import { TEMPLATES } from "./templates/index.mjs";
import { resolvePalette, drawBackground } from "./lib/palette.mjs";
import { cameraFor, drawEventOverlays, drawAmbientBreath } from "./lib/events.mjs";

const require_ = createRequire(import.meta.url);

function parseArgs(argv) {
  const scenePath = argv[0];
  const outPath = argv[1] ?? "out.mp4";
  if (!scenePath || !existsSync(scenePath)) {
    console.error("usage: node render.mjs <scene.json> <out.mp4>");
    process.exit(2);
  }
  return { scenePath, outPath };
}

async function preloadImages(props) {
  // Preload any string props ending in an image extension into __img keys
  // (templates draw preloaded Image objects; canvas loadImage is async).
  const IMG_RE = /\.(png|jpe?g|webp)$/i;
  for (const [k, v] of Object.entries(props)) {
    if (typeof v === "string" && IMG_RE.test(v) && existsSync(v)) {
      props[`__${k.replace(/_image$/, "_img").replace(/image$/, "img")}`] =
        await loadImage(v);
    } else if (typeof v === "string" && k === "map_image" && existsSync(v)) {
      props.__map_img = await loadImage(v);
    } else if (v && typeof v === "object") {
      await preloadImages(v);
    }
  }
}

async function main() {
  const { scenePath, outPath } = parseArgs(process.argv.slice(2));
  const scene = JSON.parse(readFileSync(scenePath, "utf-8"));
  const templateName = String(scene.template ?? "");
  const tpl = TEMPLATES[templateName];
  if (!tpl) {
    console.error(`unknown template: ${templateName} (known: ${Object.keys(TEMPLATES).join(", ")})`);
    process.exit(2);
  }
  const W = Number(scene.width ?? 1920);
  const H = Number(scene.height ?? 1080);
  const fps = Number(scene.fps ?? 30);
  const duration = Number(scene.duration_sec ?? 3.0);
  const totalFrames = Math.max(1, Math.round(duration * fps));
  const palette = resolvePalette(scene.style);
  const props = scene.props ?? {};
  await preloadImages(props);

  const canvas = createCanvas(W, H);
  const ctx = canvas.getContext("2d");

  const ffmpeg = spawnSync !== undefined ? null : null; // (spawn below)
  const { spawn } = await import("node:child_process");
  const ff = spawn("ffmpeg", [
    "-y",
    "-f", "rawvideo",
    "-pix_fmt", "rgba",
    "-s", `${W}x${H}`,
    "-r", String(fps),
    "-i", "-",
    "-an",
    "-c:v", "libx264", "-crf", "20", "-preset", "medium",
    "-pix_fmt", "yuv420p",
    outPath,
  ], { stdio: ["pipe", "ignore", "pipe"] });
  let ffErr = "";
  ff.stderr.on("data", (d) => { ffErr += d; if (ffErr.length > 8000) ffErr = ffErr.slice(-4000); });

  for (let frame = 0; frame < totalFrames; frame++) {
    const t = frame / totalFrames;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalAlpha = 1;
    drawBackground(ctx, W, H, palette);

    // ── V4 §4/§16 event layer: cues may arrive as compiled ops
    // (props.event_cues) or as raw template cues (props.micro_events);
    // raw cues get a minimal deterministic mapping so every shot has
    // discrete events regardless of adapter vintage.
    const cues = props.event_cues ?? minimalCues(props.micro_events, totalFrames);
    const cam = cameraFor(cues, frame, W, H);
    ctx.save();
    if (cam.scale !== 1 || cam.dx || cam.dy) {
      ctx.translate(W / 2 + cam.dx, H / 2 + cam.dy);
      ctx.scale(cam.scale, cam.scale);
      ctx.translate(-W / 2, -H / 2);
    }
    tpl(ctx, { W, H }, props, t, palette,
      await import("./lib/palette.mjs"));
    ctx.restore();
    drawEventOverlays(ctx, W, H, cues, frame, fps);
    drawAmbientBreath(ctx, W, H, frame);

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
    ok: true, out: outPath, template: templateName,
    frames: totalFrames, width: W, height: H, fps,
  }));
}

/** Fallback mapping: raw motion-canvas cues (anim names) → minimal event
 * cues, so legacy adapters still get discrete events (§4). */
function minimalCues(raw, totalFrames) {
  const out = [];
  for (const e of raw || []) {
    const start = Math.max(0, Math.round(Number(e.t ?? 0) * totalFrames));
    const span = Math.max(2, Math.round(Number(e.duration ?? 1) * totalFrames));
    const amp = Math.max(0.35, Number(e.intensity ?? 0.5));
    const anim = String(e.anim || "ambient");
    if (anim === "bg_shift") {
      const dark = String(e.text || "").toLowerCase().includes("dark");
      out.push({ start, end: start + Math.min(span, 4),
        type: dark ? "darken" : "flash", amp: 0.3 * amp });
    } else if (anim === "shake_flash" || anim === "impact") {
      out.push({ start, end: start + 2, type: "flash", amp: 0.5 });
      out.push({ start, end: start + 5, type: "shake", amp: 0.02, seed: start });
    } else if (anim === "hard_swap" || anim === "cut") {
      out.push({ start, end: start + 3, type: "cut", amp: 0.4 });
    } else if (anim === "zoom_pulse" || anim === "camera_accel") {
      out.push({ start, end: start + Math.max(3, span), type: "zoom_kick",
        amp: 0.06 * amp });
    } else if (anim === "enter" || anim === "fly_in") {
      out.push({ start, end: start + span, type: "overlay", kind: "flock",
        seed: start + 3 });
    } else if (anim === "move" || anim === "exit" || anim === "morph") {
      out.push({ start, end: start + span, type: "overlay", kind: "run",
        seed: start + 5 });
    } else if (anim === "ambient") {
      out.push({ start, end: start + span, type: "overlay", kind: "dust",
        seed: start + 7 });
    }
  }
  return out;
}

main().catch((e) => { console.error(e); process.exit(1); });
