import React from "react";
import { Composition } from "remotion";
import BenchA from "./scenes/BenchA";
import BenchB from "./scenes/BenchB";
import BenchC from "./scenes/BenchC";
import BenchD from "./scenes/BenchD";

export const FPS = 30;
export const W = 1080;
export const H = 1920;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition id="BenchA" component={BenchA} durationInFrames={210} fps={FPS} width={W} height={H} />
      <Composition id="BenchB" component={BenchB} durationInFrames={210} fps={FPS} width={W} height={H} />
      <Composition id="BenchC" component={BenchC} durationInFrames={240} fps={FPS} width={W} height={H} />
      <Composition id="BenchD" component={BenchD} durationInFrames={210} fps={FPS} width={W} height={H} />
    </>
  );
};
