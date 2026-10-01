import React from "react";
import { AbsoluteFill, Audio, Img, interpolate, staticFile, useCurrentFrame } from "remotion";

/**
 * V16 WP5 — brand intro sting: an overlay (not a pre-roll, DESIGN.md S4)
 * under the first words. Reuses the WP6 procedural ink-bloom PNG
 * (`engine.brand.ink_bloom_overlay`) and sting audio
 * (`engine.brand.sting_audio`) staged by `engine.v16_compose` — no visual
 * synthesis is reimplemented in TS.
 */
export interface StingProps {
  durationInFrames: number;
  imageSrc: string;
  audioSrc?: string | null;
}

export const Sting: React.FC<StingProps> = ({ durationInFrames, imageSrc, audioSrc }) => {
  const frame = useCurrentFrame();
  if (frame >= durationInFrames) return null;
  const opacity = interpolate(
    frame,
    [0, durationInFrames * 0.3, durationInFrames * 0.7, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  return (
    <AbsoluteFill>
      <Img src={staticFile(imageSrc)} style={{ width: "100%", height: "100%", opacity }} />
      {audioSrc ? <Audio src={staticFile(audioSrc)} /> : null}
    </AbsoluteFill>
  );
};

export default Sting;
