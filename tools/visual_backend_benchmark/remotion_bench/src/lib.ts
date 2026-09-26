import spec from "./spec.json";

export type Palette = {
  bg_deep: string;
  bg_mid: string;
  accent_warm: string;
  accent_cool: string;
  ink: string;
  ink_dim: string;
  line: string;
  shadow: string;
};

export const PALETTE = spec.style_bible.palette as Palette;
export const FONT = spec.style_bible.typography.family + ", sans-serif";
export const SEED: number = spec.seed;

export const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));
export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;
export const easeInOutCubic = (t: number): number =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
export const easeOutCubic = (t: number): number => 1 - Math.pow(1 - t, 3);

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Continuous camera transform (floating-point, single rescale downstream). */
export const camTransform = (s: number, cx = 540, cy = 960): string =>
  `translate(${cx} ${cy}) scale(${s}) translate(${-cx} ${-cy})`;

export const pt = (x: number, y: number): string => `${x.toFixed(2)},${y.toFixed(2)}`;
