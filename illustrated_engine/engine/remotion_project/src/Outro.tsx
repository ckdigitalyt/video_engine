import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";

/**
 * V16 WP5 — brand outro: a stamp over the FINAL MOVING footage, not a
 * static end screen (DESIGN.md S4 "there is no static end screen"). Reuses
 * the WP6 procedural seal-badge PNG (`engine.brand.seal_badge`) staged by
 * `engine.v16_compose`. Rendered as an overlay over the tail of the last
 * scene's own Series.Sequence — it never extends the timeline.
 */
export interface OutroProps {
  totalDurationInFrames: number;
  durationInFrames: number;
  imageSrc: string;
}

export const Outro: React.FC<OutroProps> = ({
  totalDurationInFrames,
  durationInFrames,
  imageSrc,
}) => {
  const frame = useCurrentFrame();
  const start = totalDurationInFrames - durationInFrames;
  const local = frame - start;
  if (local < 0) return null;
  const opacity = interpolate(local, [0, durationInFrames * 0.25], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-end" }}>
      <Img
        src={staticFile(imageSrc)}
        style={{ width: 220, height: "auto", opacity, marginBottom: 140 }}
      />
    </AbsoluteFill>
  );
};

export default Outro;
