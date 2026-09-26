import React, { useMemo } from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import {
  PALETTE as P,
  FONT,
  SEED,
  clamp01,
  easeInOutCubic,
  easeOutCubic,
  mulberry32,
} from "../lib";

/**
 * TEST B — STORY INFOGRAPHIC
 * Circular deep-time scale: vector ring reveal, epoch labels, highlight
 * segment, giant integrated number, measurement leader. Static camera,
 * animated geometry — part of the illustrated world, not a dashboard.
 */
const EPOCHS = ["4.6 BYA", "3.8 BYA", "2.5 BYA", "0.6 BYA", "NOW"];
const CX = 540;
const CY = 900;
const R = 420;

const BenchB: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const p = frame / (durationInFrames - 1);

  const f = 0.75 * easeInOutCubic(clamp01((p - 0.05) / 0.75));
  const CIRC = 2 * Math.PI * R;
  const value = 4.6 * easeInOutCubic(clamp01((p - 0.1) / 0.7));
  const hlOp = easeOutCubic(clamp01((p - 0.55) / 0.15));
  const numOp = easeOutCubic(clamp01((p - 0.1) / 0.1));
  const leaderOp = easeOutCubic(clamp01((p - 0.6) / 0.15));

  const stars = useMemo(() => {
    const r = mulberry32(SEED + 7);
    return Array.from({ length: 60 }, () => ({
      x: r() * 1080,
      y: r() * 1200,
      rad: 1 + r() * 2.2,
      ph: r() * 6,
    }));
  }, []);

  return (
    <AbsoluteFill style={{ backgroundColor: P.bg_deep }}>
      <svg width="100%" height="100%" viewBox="0 0 1080 1920">
        <defs>
          <radialGradient id="bBg" cx="50%" cy="45%" r="80%">
            <stop offset="0%" stopColor={P.bg_mid} />
            <stop offset="100%" stopColor={P.bg_deep} />
          </radialGradient>
          <filter id="bGlow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="14" />
          </filter>
        </defs>
        <rect width="1080" height="1920" fill="url(#bBg)" />
        {stars.map((s, i) => (
          <circle key={i} cx={s.x} cy={s.y} r={s.rad} fill={P.ink} opacity={0.25 + 0.25 * Math.sin(frame / 18 + s.ph)} />
        ))}

        {/* ring world — sweep starts at 12 o'clock */}
        <g transform={`rotate(-90 ${CX} ${CY})`}>
          <circle cx={CX} cy={CY} r={R} fill="none" stroke={P.line} strokeWidth={26} strokeLinecap="round" />
          <circle
            cx={CX}
            cy={CY}
            r={R}
            fill="none"
            stroke={P.accent_cool}
            strokeWidth={26}
            strokeLinecap="round"
            strokeDasharray={`${CIRC * f} ${CIRC}`}
          />
          <g opacity={hlOp}>
            <circle
              cx={CX}
              cy={CY}
              r={R}
              fill="none"
              stroke={P.accent_warm}
              strokeWidth={30}
              strokeLinecap="round"
              strokeDasharray={`${CIRC * 0.1875} ${CIRC}`}
              strokeDashoffset={-CIRC * 0.5625}
              opacity={0.75 + 0.25 * Math.sin(frame / 8)}
              filter="url(#bGlow)"
            />
          </g>
          {Array.from({ length: 36 }, (_, i) => {
            const a = (i / 36) * Math.PI * 2;
            const inner = i % 9 === 0 ? R - 34 : R - 22;
            return (
              <line
                key={i}
                x1={CX + Math.cos(a) * inner}
                y1={CY + Math.sin(a) * inner}
                x2={CX + Math.cos(a) * (R - 8)}
                y2={CY + Math.sin(a) * (R - 8)}
                stroke={P.ink_dim}
                strokeWidth={i % 9 === 0 ? 4 : 2}
                opacity={0.7}
              />
            );
          })}
        </g>

        {/* epoch labels appear as the sweep passes them */}
        {EPOCHS.map((e, i) => {
          const frac = (i / 4) * 0.75;
          const ang = -Math.PI / 2 + frac * Math.PI * 2;
          const lx = CX + Math.cos(ang) * (R + 74);
          const ly = CY + Math.sin(ang) * (R + 74);
          const appear = easeOutCubic(clamp01((f - frac + 0.02) / 0.06));
          return (
            <g key={i} opacity={appear} transform={`translate(0 ${(1 - appear) * 14})`}>
              <circle cx={lx} cy={ly} r={6} fill={P.accent_warm} />
              <text x={lx} y={ly - 18} textAnchor="middle" fill={P.ink} fontFamily={FONT} fontWeight={700} fontSize={34} letterSpacing={2}>
                {e}
              </text>
            </g>
          );
        })}

        {/* giant integrated number */}
        <g opacity={numOp}>
          <text x={CX} y={CY + 40} textAnchor="middle" fill={P.ink} fontFamily={FONT} fontWeight={700} fontSize={170} letterSpacing={4}>
            {value.toFixed(1)}
          </text>
          <text x={CX} y={CY + 112} textAnchor="middle" fill={P.ink_dim} fontFamily={FONT} fontSize={36} letterSpacing={8}>
            BILLION YEARS
          </text>
        </g>

        {/* measurement leader */}
        <g opacity={leaderOp}>
          <path
            d={`M ${CX + R * 0.71} ${CY + R * 0.71} L 900 1420 L 1020 1420`}
            fill="none"
            stroke={P.ink}
            strokeWidth={2.5}
            strokeLinecap="round"
          />
          <circle cx={CX + R * 0.71} cy={CY + R * 0.71} r={7} fill={P.accent_warm} />
          <text x={1020} y={1408} textAnchor="end" fill={P.ink} fontFamily={FONT} fontWeight={700} fontSize={34} letterSpacing={3}>
            EARTH TIMELINE
          </text>
          <text x={1020} y={1452} textAnchor="end" fill={P.ink_dim} fontFamily={FONT} fontSize={26} letterSpacing={2}>
            compressed to one arc
          </text>
        </g>

        {/* title support line */}
        <text x={540} y={220} textAnchor="middle" fill={P.ink_dim} fontFamily={FONT} fontWeight={700} fontSize={40} letterSpacing={6}>
          DEEP TIME
        </text>
      </svg>
    </AbsoluteFill>
  );
};

export default BenchB;
