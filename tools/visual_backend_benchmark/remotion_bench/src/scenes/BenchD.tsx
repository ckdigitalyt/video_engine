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
 * TEST D — ENVIRONMENT / SCENE
 * Stylized fog-oasis dusk: sky gradient, stars, moon, three mountain ranges,
 * swaying tree line, salt pan, foreground rocks, drifting fog banks.
 * Camera: lateral pan with 5-band parallax; contextual labels with leaders.
 * Proves the system can build a WORLD, not a card.
 */
const ridge = (seed: number, baseY: number, amp: number): string => {
  const r = mulberry32(seed);
  let d = `M -250 ${baseY + 600} L -250 ${baseY} `;
  let x = -250;
  while (x < 1350) {
    x += 90 + r() * 110;
    const peak = baseY - amp * (0.35 + r() * 0.65);
    const mid = x - 45 - r() * 40;
    d += `L ${mid} ${baseY - amp * 0.25 - r() * amp * 0.2} L ${x} ${peak} `;
  }
  d += `L 1350 ${baseY} L 1350 ${baseY + 600} Z`;
  return d;
};

const BenchD: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const p = frame / (durationInFrames - 1);
  const pan = -180 * easeInOutCubic(p);
  const par = (f: number) => `translate(${pan * f} 0)`;

  const stars = useMemo(() => {
    const r = mulberry32(SEED + 11);
    return Array.from({ length: 55 }, () => ({
      x: r() * 1500 - 150,
      y: r() * 900,
      rad: 1 + r() * 2,
      ph: r() * 6,
    }));
  }, []);
  const trees = useMemo(() => {
    const r = mulberry32(SEED + 12);
    return Array.from({ length: 8 }, (_, i) => ({
      x: -60 + i * 160 + r() * 60,
      s: 0.75 + r() * 0.5,
      ph: r() * 6,
    }));
  }, []);
  const cracks = useMemo(() => {
    const r = mulberry32(SEED + 13);
    return Array.from({ length: 7 }, () => ({
      x: r() * 1200 - 60,
      len: 120 + r() * 260,
      sk: (r() - 0.5) * 80,
    }));
  }, []);

  const farD = useMemo(() => ridge(SEED + 21, 1240, 300), []);
  const midD = useMemo(() => ridge(SEED + 22, 1330, 230), []);

  const labelOp = easeOutCubic(clamp01((p - 0.4) / 0.2));
  const fogX1 = 420 - 140 * Math.sin(frame / 95);
  const fogX2 = 700 - 120 * Math.cos(frame / 80);

  return (
    <AbsoluteFill style={{ backgroundColor: P.bg_deep }}>
      <svg width="100%" height="100%" viewBox="0 0 1080 1920">
        <defs>
          <linearGradient id="dSky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={P.bg_deep} />
            <stop offset="55%" stopColor={P.bg_mid} />
            <stop offset="78%" stopColor="#3C6E71" />
            <stop offset="88%" stopColor={P.accent_warm} stopOpacity="0.55" />
            <stop offset="100%" stopColor={P.accent_warm} stopOpacity="0.2" />
          </linearGradient>
          <filter id="dGlow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="26" />
          </filter>
          <filter id="dFog" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="30" />
          </filter>
        </defs>

        <rect width="1080" height="1920" fill="url(#dSky)" />

        {/* sky — parallax 0.1 */}
        <g transform={par(0.1)}>
          {stars.map((s, i) => (
            <circle key={i} cx={s.x} cy={s.y} r={s.rad} fill={P.ink} opacity={0.25 + 0.25 * Math.sin(frame / 18 + s.ph)} />
          ))}
          <circle cx={780} cy={430} r={64} fill={P.ink} opacity={0.92} />
          <circle cx={780} cy={430} r={110} fill={P.ink} opacity={0.25} filter="url(#dGlow)" />
          <circle cx={756} cy={412} r={12} fill={P.bg_mid} opacity={0.5} />
          <circle cx={800} cy={448} r={8} fill={P.bg_mid} opacity={0.4} />
        </g>

        {/* mountain ranges — parallax 0.3 / 0.55 */}
        <g transform={par(0.3)}>
          <path d={farD} fill="#1B3A54" stroke={P.line} strokeWidth={3} />
        </g>
        <g transform={par(0.55)}>
          <path d={midD} fill="#12293E" stroke={P.line} strokeWidth={3} />
        </g>

        {/* fog banks — parallax 1.3 plus own drift */}
        <g transform={par(1.3)}>
          <ellipse cx={fogX1} cy={1290} rx={430} ry={90} fill={P.ink_dim} filter="url(#dFog)" opacity={0.18} />
          <ellipse cx={fogX2} cy={1360} rx={380} ry={70} fill={P.ink_dim} filter="url(#dFog)" opacity={0.14} />
        </g>

        {/* tree line — parallax 0.85, gentle sway */}
        <g transform={par(0.85)}>
          {trees.map((t, i) => {
            const sway = Math.sin(frame / 50 + t.ph) * 1.2;
            return (
              <g key={i} transform={`translate(${t.x} 1420) scale(${t.s}) rotate(${sway} 0 0)`}>
                <rect x={-7} y={-26} width={14} height={30} fill="#0E1B26" />
                <polygon points="0,-150 -52,-52 52,-52" fill="#0F2A38" stroke={P.line} strokeWidth={2} />
                <polygon points="0,-110 -62,4 62,4" fill="#123448" stroke={P.line} strokeWidth={2} />
              </g>
            );
          })}
        </g>

        {/* salt pan — parallax 1.1 */}
        <g transform={par(1.1)}>
          <rect x={-250} y={1450} width={1600} height={500} fill="#153247" />
          <path d="M -250 1450 L 1350 1450" stroke={P.accent_warm} strokeWidth={3} opacity={0.4} />
          {cracks.map((c, i) => (
            <path
              key={i}
              d={`M ${c.x} 1520 L ${c.x + c.sk} ${1520 + c.len * 0.4} L ${c.x + c.sk * 1.6} ${1520 + c.len * 0.75}`}
              stroke={P.bg_deep}
              strokeWidth={4}
              fill="none"
              opacity={0.7}
              strokeLinecap="round"
            />
          ))}
        </g>

        {/* foreground rocks — parallax 1.45 */}
        <g transform={par(1.45)}>
          <ellipse cx={180} cy={1810} rx={210} ry={110} fill="#0A1826" />
          <ellipse cx={880} cy={1860} rx={260} ry={120} fill="#0A1826" />
        </g>

        {/* contextual labels with leader lines */}
        <g opacity={labelOp}>
          <path d="M 420 1290 L 300 1150 L 170 1150" fill="none" stroke={P.ink} strokeWidth={2.5} strokeLinecap="round" />
          <circle cx={420} cy={1290} r={7} fill={P.accent_warm} />
          <text x={170} y={1138} fill={P.ink} fontFamily={FONT} fontWeight={700} fontSize={34} letterSpacing={3}>FOG BANK — 2 KM</text>
          <text x={170} y={1180} fill={P.ink_dim} fontFamily={FONT} fontSize={24} letterSpacing={2}>the desert drinks here</text>

          <path d="M 870 1560 L 940 1640 L 1010 1640" fill="none" stroke={P.ink} strokeWidth={2.5} strokeLinecap="round" />
          <circle cx={870} cy={1560} r={7} fill={P.accent_warm} />
          <text x={1010} y={1628} textAnchor="end" fill={P.ink} fontFamily={FONT} fontWeight={700} fontSize={34} letterSpacing={3}>SALT PAN</text>
        </g>

        {/* title support line */}
        <text x={540} y={180} textAnchor="middle" fill={P.ink_dim} fontFamily={FONT} fontWeight={700} fontSize={38} letterSpacing={6}>
          WHERE FOG BECOMES WATER
        </text>
      </svg>
    </AbsoluteFill>
  );
};

export default BenchD;
