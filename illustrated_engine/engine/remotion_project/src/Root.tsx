import React from "react";
import { Composition } from "remotion";
import SceneComposition, { CompiledProps, EMPTY_PROPS } from "./SceneComposition";
import Short, { EMPTY_SHORT_PROPS, ShortProps, shortDurationInFrames } from "./Short";

/**
 * Two compositions in one bundle:
 * - "SceneIR": the existing per-scene renderer (engine/scene_renderer.py),
 *   unchanged — WP7's per-template stills and today's live per-scene
 *   render pass both still use it.
 * - "Short" (V16 WP5, DESIGN.md 15.2): one `<Series>` composition per
 *   video, props built by engine.v16_compose.build_short_props.
 * calculateMetadata derives duration/size/fps from the compiled props in
 * both cases so one bundle serves every scene/video.
 */
export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="SceneIR"
        component={SceneComposition}
        durationInFrames={EMPTY_PROPS.durationInFrames}
        fps={EMPTY_PROPS.fps}
        width={EMPTY_PROPS.width}
        height={EMPTY_PROPS.height}
        defaultProps={EMPTY_PROPS}
        calculateMetadata={({ props }: { props: CompiledProps }) => ({
          durationInFrames: props.durationInFrames,
          fps: props.fps,
          width: props.width,
          height: props.height,
        })}
      />
      <Composition
        id="Short"
        component={Short}
        durationInFrames={1}
        fps={EMPTY_SHORT_PROPS.fps}
        width={EMPTY_SHORT_PROPS.width}
        height={EMPTY_SHORT_PROPS.height}
        defaultProps={EMPTY_SHORT_PROPS}
        calculateMetadata={({ props }: { props: ShortProps }) => ({
          durationInFrames: shortDurationInFrames(props),
          fps: props.fps,
          width: props.width,
          height: props.height,
        })}
      />
    </>
  );
};
