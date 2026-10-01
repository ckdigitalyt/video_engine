#!/usr/bin/env node
// V16 WP5 — pre-bundled @remotion/renderer driver for the "Short" composition.
// One webpack bundle serves every call this process makes (renderStill per
// sampled frame, or one renderMedia for a full video), instead of the
// per-scene backend's `npx remotion still|render` (one CLI cold start per
// call). Called from engine.v16_compose (never from the live pipeline —
// this path is not wired in until the WP5 parity test passes).
//
// Usage:
//   node render_short.mjs stills <props.json> <out_dir> <frame,frame,...>
//   node render_short.mjs render <props.json> <out.mp4>

import path from "node:path";
import fs from "node:fs";
import { bundle } from "@remotion/bundler";
import { renderMedia, renderStill, selectComposition } from "@remotion/renderer";

const [, , mode, propsPath, outArg, framesArg] = process.argv;

async function main() {
  if (!mode || !propsPath || !outArg) {
    console.error("usage: render_short.mjs <stills|render> <props.json> <out> [frames]");
    process.exit(2);
  }
  const inputProps = JSON.parse(fs.readFileSync(propsPath, "utf8"));
  const serveUrl = await bundle({
    entryPoint: path.join(process.cwd(), "src", "index.ts"),
    onProgress: () => {},
  });
  const composition = await selectComposition({
    serveUrl,
    id: "Short",
    inputProps,
  });

  if (mode === "stills") {
    const frames = (framesArg || "").split(",").filter(Boolean).map(Number);
    fs.mkdirSync(outArg, { recursive: true });
    for (const frame of frames) {
      const output = path.join(outArg, `f_${frame}.png`);
      await renderStill({ composition, serveUrl, output, frame, inputProps });
      console.log(`wrote ${output}`);
    }
    return;
  }

  if (mode === "render") {
    fs.mkdirSync(path.dirname(outArg), { recursive: true });
    await renderMedia({
      composition,
      serveUrl,
      codec: "h264",
      crf: 18,
      pixelFormat: "yuv420p",
      outputLocation: outArg,
      inputProps,
    });
    console.log(`wrote ${outArg}`);
    return;
  }

  console.error(`unknown mode ${mode}`);
  process.exit(2);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
