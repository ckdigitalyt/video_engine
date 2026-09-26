import React, { useMemo } from "react";
import {
  AbsoluteFill,
  Audio,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import {
  PALETTE as P,
  FONT,
  SEED,
  clamp01,
  easeInOutCubic,
  easeOutCubic,
  mulberry32,
  camTransform,
} from "../lib";

/**
 * TEST A — RICH SUBJECT SCENE
 * Layered illustrated cell: background, atmosphere, subject (membrane,
 * texture, organelles, nucleus), shadow, semantic annotation, foreground.
 * Camera: eased push-in with per-layer parallax multipliers. Audio-sync test.
 */
const BenchA: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const p = frame / (durationInFrames - 1);

  const push = 1 + 0.15 * easeInOutCubic(clamp01(p / 0.9));

  const squiggles = useMemo(() => {
    const r = mulberry32(SEED + 1);
    return Array.from({ length: 9 }, (_, i) => {
      const a = (i / 9) * Math.PI * 2 + r() * 0.6;
      const rad = 240 + r() * 110;
      return {
        x: 540 + Math.cos(a) * rad,
        y: 960 + Math.sin(a) * rad,
        len: 60 + r() * 90,
        rot: (a * 180) / Math.PI + r() * 50,
        w: 1.4 + r() * 1.2,
      };
    });
  }, []);

  const organelles = useMemo(() => {
    const r = mulberry32(SEED + 2);
    return Array.from({ length: 6 }, () => ({
      x: 540 + (r() - 0.5) * 470,
      y: 960 + (r() - 0.5) * 470,
      rx: 26 + r() * 44,
      ry: 16 + r() * 28,
      rot: r() * 180,
      ph: r() * Math.PI * 2,
    }));
  }, []);

  const blobs = useMemo(() => {
    const r = mulberry32(SEED + 3);
    return Array.from({ length: 3 }, () => ({
      x: 200 + r() * 700,
      y: 300 + r() * 1300,
      rx: 220 + r() * 200,
      ry: 90 + r() * 120,
      sp: 0.4 + r() * 0.5,
      ph: r() * 6,
      op: 0.08 + r() * 0.08,
    }));
  }, []);

  const annAppear = easeOutCubic(clamp01((p - 0.35) / 0.2));

  return (
    <AbsoluteFill style={{ backgroundColor: P.shadow }}>
      <Audio src={staticFile("tone.wav")} volume={0.12} />
      <svg width="100%" height="100%" viewBox="0 0 1080 1920">
        <defs>
          <radialGradient id="aBg" cx="50%" cy="42%" r="75%">
            <stop offset="0%" stopColor={P.bg_mid} />
            <stop offset="100%" stopColor={P.bg_deep} />
          </radialGradient>
          <radialGradient id="aMem" cx="42%" cy="36%" r="80%">
            <stop offset="0%" stopColor={P.accent_cool} stopOpacity="0.85" />
            <stop offset="55%" stopColor={P.bg_mid} />
            <stop offset="100%" stopColor={P.bg_deep} />
          </radialGradient>
          <radialGradient id="aNuc" cx="40%" cy="35%" r="75%">
            <stop offset="0%" stopColor={P.accent_warm} />
            <stop offset="70%" stopColor="#B06E32" />
            <stop offset="100%" stopColor={P.shadow} />
          </radialGradient>
          <filter id="aGlow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="18" />
          </filter>
          <filter id="aSoft" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="34" />
          </filter>
        </defs>

        <rect width="1080" height="1920" fill="url(#aBg)" />

        {/* atmosphere — parallax 0.7 */}
        <g transform={camTransform(1 + (push - 1) * 0.7)}>
          {blobs.map((b, i) => (
            <ellipse
              key={i}
              cx={b.x + 40 * Math.sin(frame / 60 + b.ph)}
              cy={b.y + 24 * Math.cos(frame / 80 + b.ph)}
              rx={b.rx}
              ry={b.ry}
              fill={P.accent_cool}
              opacity={b.op}
              filter="url(#aSoft)"
            />
          ))}
        </g>

        {/* contact shadow */}
        <ellipse cx={540} cy={1430} rx={330} ry={54} fill={P.shadow} opacity={0.5} filter="url(#aSoft)" />

        {/* subject — parallax 1.0, subtle idle motion */}
        <g transform={camTransform(push)}>
          <g transform={`translate(0 ${Math.sin(frame / 45) * 8})`}>
            <circle cx={540} cy={960} r={380} fill="url(#aMem)" stroke={P.line} strokeWidth={3} />
            {squiggles.map((s, i) => (
              <path
                key={i}
                d={`M ${s.x - s.len / 2} ${s.y} q ${s.len / 4} -14 ${s.len / 2} 0 t ${s.len / 4} 6`}
                fill="none"
                stroke={P.ink_dim}
                strokeWidth={s.w}
                opacity={0.28}
                strokeLinecap="round"
                transform={`rotate(${s.rot} ${s.x} ${s.y})`}
              />
            ))}
            {organelles.map((o, i) => (
              <ellipse
                key={i}
                cx={o.x}
                cy={o.y + 6 * Math.sin(frame / 40 + o.ph)}
                rx={o.rx}
                ry={o.ry}
                fill={P.accent_cool}
                opacity={0.22}
                stroke={P.line}
                strokeWidth={2}
                transform={`rotate(${o.rot + frame * 0.02} ${o.x} ${o.y})`}
              />
            ))}
            <circle cx={540} cy={960} r={150} fill="url(#aNuc)" stroke={P.accent_warm} strokeWidth={2.5} opacity={0.97} />
            <circle
              cx={540}
              cy={960}
              r={196}
              fill="none"
              stroke={P.accent_warm}
              strokeWidth={1.5}
              opacity={0.5 + 0.2 * Math.sin(frame / 12)}
              filter="url(#aGlow)"
            />
            <circle cx={498} cy={918} r={44} fill={P.ink} opacity={0.25} filter="url(#aGlow)" />
          </g>
        </g>

        {/* semantic annotation — screen-stable, draws on */}
        <g opacity={annAppear}>
          <circle cx={646} cy={878} r={7} fill={P.accent_warm} />
          <path
            d="M 646 878 L 760 700 L 950 700"
            fill="none"
            stroke={P.ink}
            strokeWidth={2.5}
            strokeLinecap="round"
            pathLength={1}
            strokeDasharray={1}
            strokeDashoffset={1 - annAppear}
          />
          <text x={950} y={688} textAnchor="end" fill={P.ink} fontFamily={FONT} fontWeight={700} fontSize={40} letterSpacing={3}>
            NUCLEUS
          </text>
          <text x={950} y={736} textAnchor="end" fill={P.ink_dim} fontFamily={FONT} fontSize={28} letterSpacing={2}>
            the control center
          </text>
        </g>

        {/* foreground — parallax 1.35 */}
        <g transform={camTransform(1 + (push - 1) * 1.35)} opacity={0.5}>
          <path d="M -80 1560 Q 540 1420 1160 1600" fill="none" stroke={P.bg_deep} strokeWidth={90} strokeLinecap="round" />
          <path d="M -80 1700 Q 540 1580 1160 1740" fill="none" stroke={P.bg_deep} strokeWidth={60} strokeLinecap="round" opacity={0.7} />
        </g>
      </svg>
    </AbsoluteFill>
  );
};

export default BenchA;
