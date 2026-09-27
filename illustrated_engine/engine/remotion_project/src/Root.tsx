import React from "react";
import { Composition } from "remotion";
import SceneComposition, { CompiledProps, EMPTY_PROPS } from "./SceneComposition";

/**
 * Single dynamic composition. The Python adapter (engine/scene_renderer.py)
 * compiles a validated Scene IR spec into props (frames domain) and passes
 * them via `--props <file>`; calculateMetadata derives duration/size/fps
 * from the compiled props so one composition serves every scene.
 */
export const RemotionRoot: React.FC = () => {
  return (
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
  );
};
