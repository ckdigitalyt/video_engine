import { makeScene2D, Circle, Txt, Line } from "@motion-canvas/2d";
import { createRef, waitFor, all, easeInOutCubic } from "@motion-canvas/core";

/**
 * V14 secondary-candidate probe — Motion Canvas equivalent of the shared
 * spec: one rich-ish subject (layered circle + annotation line + label),
 * camera push via view scale, deterministic timing.
 */
export default makeScene2D(function* (view) {
  const subject = createRef<Circle>();
  const halo = createRef<Circle>();
  const label = createRef<Txt>();
  const leader = createRef<Line>();

  const CY = "#7FD1C7";
  const WARM = "#F2A65A";

  view.add(
    <>
      <Circle ref={halo} size={900} stroke={WARM} lineWidth={2} opacity={0.5} />
      <Circle ref={subject} size={640} fill={CY} stroke="#2A4E6E" lineWidth={4} />
      <Line
        ref={leader}
        points={[
          [180, -120],
          [360, -260],
          [520, -260],
        ]}
        stroke={"#EAF4F4"}
        lineWidth={3}
      />
      <Txt ref={label} text={"NUCLEUS"} fill={"#EAF4F4"} fontSize={44} y={-300} x={430} fontWeight={700} />
    </>,
  );

  view.position([540, 960]);

  // camera push (semantic: slow push-in)
  const t0 = 0.0;
  yield all(subject().scale(1.15, 4, easeInOutCubic), halo().scale(1.08, 4, easeInOutCubic));

  // annotation reveal
  leader().opacity(0);
  label().opacity(0);
  yield all(leader().opacity(1, 0.6), label().opacity(1, 0.6));

  yield* waitFor(1.0);
});
