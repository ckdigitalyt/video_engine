import React from "react";
import { AbsoluteFill, Series } from "remotion";
import SceneComposition, { CompiledProps } from "./SceneComposition";
import Captions, { CaptionsProps } from "./Captions";
import Sting, { StingProps } from "./Sting";
import Outro, { OutroProps } from "./Outro";

/**
 * V16 WP5 (DESIGN.md 15.2 WP5) — one Remotion composition per video.
 * `<Series>` sequences the exact same per-scene `SceneComposition` props
 * every scene already renders with individually (`engine.scene_renderer.
 * compile_spec`), so the plate/camera/text layer is byte-for-byte the same
 * renderer as today's per-scene `remotion render` pass. `Captions` (built
 * on `@remotion/captions`), `Sting` and `Outro` replace the Python
 * chunk_png/ffmpeg-overlay and (previously unwired) brand sting/outro
 * assets, composited inside the one render instead of a separate pass.
 *
 * Props are built by `engine.v16_compose.build_short_props` — pure
 * Python, no literals here.
 */

export interface ShortScene {
  id: string;
  durationInFrames: number;
  props: CompiledProps;
}

export interface ShortProps {
  width: number;
  height: number;
  fps: number;
  scenes: ShortScene[];
  captions: CaptionsProps;
  sting?: Omit<StingProps, "durationInFrames"> & { durationInFrames: number } | null;
  outro?: Omit<OutroProps, "totalDurationInFrames"> | null;
}

export const EMPTY_SHORT_PROPS: ShortProps = {
  width: 1080,
  height: 1920,
  fps: 30,
  scenes: [],
  captions: { track: [], combineWithinMs: 40, bandTop: 1344, textColor: "#F5F2EB", activeColor: "#FFC857" },
  sting: null,
  outro: null,
};

export const shortDurationInFrames = (props: ShortProps): number =>
  Math.max(1, props.scenes.reduce((acc, s) => acc + s.durationInFrames, 0));

export const Short: React.FC<ShortProps> = (props) => {
  const total = shortDurationInFrames(props);
  return (
    <AbsoluteFill>
      <Series>
        {props.scenes.map((s) => (
          <Series.Sequence key={s.id} durationInFrames={s.durationInFrames} layout="none">
            <SceneComposition {...s.props} />
          </Series.Sequence>
        ))}
      </Series>
      <Captions {...props.captions} />
      {props.sting ? <Sting {...props.sting} /> : null}
      {props.outro ? <Outro totalDurationInFrames={total} {...props.outro} /> : null}
    </AbsoluteFill>
  );
};

export default Short;
