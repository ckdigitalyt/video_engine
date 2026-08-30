// lib/assets.mjs — asset resolution + preload against the local library.
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { loadImage } = require("canvas");

const HERE = dirname(fileURLToPath(import.meta.url));
export const LIBRARY_ROOT = resolve(HERE, "../../engine/assets/library");

/** Known library names → file paths (relative to LIBRARY_ROOT). */
export const LIBRARY = {
  t_rex: "characters/t_rex.svg",
  dino_herd: "characters/dino_herd.svg",
  dinosaur: "characters/dino_herd.svg", // generic alias
  jungle: "backdrops/jungle.svg",
  asteroid: "props/asteroid.svg",
  earth: "props/earth.svg",
  arrow: "icons/arrow.svg",
  callout: "icons/callout.svg",
  plus: "icons/plus.svg",
  marker: "icons/marker.svg",
};

/** Resolve an asset reference: library name, absolute path, or project path. */
export function resolveAssetPath(ref) {
  if (!ref) return null;
  if (LIBRARY[ref]) return join(LIBRARY_ROOT, LIBRARY[ref]);
  if (existsSync(ref)) return ref;
  const inLib = join(LIBRARY_ROOT, ref);
  if (existsSync(inLib)) return inLib;
  return null;
}

/** Collect every asset reference used in a scene and preload to Image. */
export async function preloadSceneAssets(scene) {
  const refs = new Set();
  if (scene.background && typeof scene.background === "object" && scene.background.asset) {
    refs.add(scene.background.asset);
  }
  for (const layer of scene.background?.parallax_layers ?? []) {
    if (layer.asset) refs.add(layer.asset);
  }
  for (const ch of scene.characters ?? []) refs.add(ch.type);
  for (const p of scene.props_objects ?? []) refs.add(p.type);
  const images = new Map();
  for (const ref of refs) {
    const path = resolveAssetPath(ref);
    if (path) {
      try {
        images.set(ref, await loadImage(path));
      } catch (e) {
        console.warn(`asset failed to load: ${ref} (${e.message})`);
      }
    } else {
      console.warn(`unknown asset: ${ref} (skipped)`);
    }
  }
  return images;
}

export async function loadSvg(path) {
  return loadImage(await readFile(path));
}
