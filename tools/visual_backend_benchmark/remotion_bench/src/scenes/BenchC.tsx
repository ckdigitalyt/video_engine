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
  camTransform,
} from "../lib";

/**
 * TEST C — VISUAL TRANSFORMATION (eye → tissue → DNA)
 * One continuous camera dive (S = 1 → 30, eased in log space). Deeper layers
 * live at fixed world offsets inside the pupil / cell nucleus; nested clip
 * apertures grow with S so the zoom is a single continuous semantic motion —
 * no crossfades. Persistent screen-stable anchor ring throughout.
 */
const CX = 540;
const CY = 960;

const BenchC: React.FC = () => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const p = frame / (durationInFrames - 1);
  const S = Math.pow(30, easeInOutCubic(p)); // continuous scale dive

  const eyePath = `M ${CX - 420} ${CY} C ${CX - 220} ${CY - 260}, ${CX + 220} ${CY - 260}, ${CX + 420} ${CY} C ${CX + 220} ${CY + 260}, ${CX - 220} ${CY + 260}, ${CX - 420} ${CY} Z`;

  const striations = useMemo(() => {
    return Array.from({ length: 26 }, (_, i) => {
      const a = (i / 26) * Math.PI * 2;
      return {
        x1: CX + Math.cos(a) * 78,
        y1: CY + Math.sin(a) * 78,
        x2: CX + Math.cos(a) * 200,
        y2: CY + Math.sin(a) * 200,
      };
    });
  }, []);

  const tissue = useMemo(() => {
    const r = mulberry32(SEED + 5);
    const cells = Array.from({ length: 12 }, (_, i) => {
      const a = (i / 12) * Math.PI * 2 + r() * 0.4;
      const rad = 150 + r() * 260;
      return {
        x: Math.cos(a) * rad,
        y: Math.sin(a) * rad,
        rx: 46 + r() * 30,
        ry: 36 + r() * 24,
        rot: r() * 180,
      };
    });
    const links: { x1: number; y1: number; x2: number; y2: number }[] = [];
    for (let i = 0; i < cells.length; i++) {
      const j = (i + 1) % cells.length;
      links.push({ x1: cells[i].x, y1: cells[i].y, x2: cells[j].x, y2: cells[j].y });
    }
    return { cells, links };
  }, []);

  const helix = useMemo(() => {
    let d1 = "";
    let d2 = "";
    for (let y = -700; y <= 700; y += 14) {
      const x1 = 150 * Math.sin(y / 110);
      const x2 = -150 * Math.sin(y / 110);
      d1 += `${y === -700 ? "M" : "L"} ${x1} ${y} `;
      d2 += `${y === -700 ? "M" : "L"} ${x2} ${y} `;
    }
    const rungs: { xa: number; y: number; xb: number }[] = [];
    for (let y = -660; y <= 660; y += 100) {
      rungs.push({ xa: 150 * Math.sin(y / 110), y, xb: -150 * Math.sin(y / 110) });
    }
    return { d1, d2, rungs };
  }, []);

  // label bands driven by the continuous camera scale
  const op0 = easeOutCubic(clamp01((3.2 - S) / 0.8));
  const op1 = Math.min(clamp01((S - 2.6) / 0.8), clamp01((9 - S) / 1.2));
  const op2 = easeOutCubic(clamp01((S - 8.2) / 1.2));
  const scaleText = S < 10 ? S.toFixed(1) : S.toFixed(0);

  return (
    <AbsoluteFill style={{ backgroundColor: P.bg_deep }}>
      <svg width="100%" height="100%" viewBox="0 0 1080 1920">
        <defs>
          <radialGradient id="cIris" cx="44%" cy="40%" r="75%">
            <stop offset="0%" stopColor={P.accent_cool} />
            <stop offset="60%" stopColor="#2E7D74" />
            <stop offset="100%" stopColor={P.bg_deep} />
          </radialGradient>
          <radialGradient id="cBg" cx="50%" cy="48%" r="80%">
            <stop offset="0%" stopColor={P.bg_mid} />
            <stop offset="100%" stopColor={P.bg_deep} />
          </radialGradient>
          <clipPath id="cPupil">
            <circle cx={CX} cy={CY} r={64 * S} />
          </clipPath>
          <clipPath id="cNucleus">
            <circle cx={CX} cy={CY} r={18 * S} />
          </clipPath>
        </defs>

        <rect width="1080" height="1920" fill="url(#cBg)" />

        {/* LAYER 1 — EYE (magnifies with camera) */}
        <g transform={camTransform(S)}>
          <path d={eyePath} fill="#F5EFE6" stroke={P.line} strokeWidth={4} />
          <circle cx={CX} cy={CY} r={210} fill="url(#cIris)" stroke={P.line} strokeWidth={3} />
          {striations.map((s, i) => (
            <line key={i} x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} stroke={P.bg_deep} strokeWidth={3} opacity={0.5} />
          ))}
          <circle cx={CX} cy={CY} r={64} fill={P.shadow} />
        </g>

        {/* LAYER 2 — TISSUE, revealed through the pupil aperture (r = 64·S screen) */}
        <g clipPath="url(#cPupil)">
          <g transform={camTransform(S)}>
            <g transform={`translate(${CX} ${CY}) scale(0.25)`}>
              {tissue.links.map((l, i) => (
                <line key={i} x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2} stroke={P.line} strokeWidth={6} opacity={0.6} />
              ))}
              {tissue.cells.map((c, i) => (
                <ellipse
                  key={i}
                  cx={c.x}
                  cy={c.y}
                  rx={c.rx}
                  ry={c.ry}
                  fill="#1E5A54"
                  stroke={P.accent_cool}
                  strokeWidth={5}
                  opacity={0.92}
                  transform={`rotate(${c.rot} ${c.x} ${c.y})`}
                />
              ))}
              {/* the cell of interest: membrane + dark nucleus (world r = 18) */}
              <circle cx={0} cy={0} r={110} fill="#17605A" stroke={P.accent_warm} strokeWidth={7} />
              <circle cx={0} cy={0} r={72} fill={P.shadow} stroke={P.accent_warm} strokeWidth={4} opacity={0.95} />
            </g>
          </g>
        </g>

        {/* LAYER 3 — DNA, revealed through the cell nucleus aperture (r = 18·S screen) */}
        <g clipPath="url(#cNucleus)">
          <g transform={camTransform(S)}>
            <g transform={`translate(${CX} ${CY}) scale(0.05)`}>
              <path d={helix.d1} fill="none" stroke={P.accent_warm} strokeWidth={16} strokeLinecap="round" />
              <path d={helix.d2} fill="none" stroke={P.accent_cool} strokeWidth={16} strokeLinecap="round" />
              {helix.rungs.map((r, i) => (
                <g key={i}>
                  <line x1={r.xa} y1={r.y} x2={r.xb} y2={r.y} stroke={P.ink} strokeWidth={9} opacity={0.85} />
                  <circle cx={r.xa} cy={r.y} r={14} fill={P.accent_warm} />
                  <circle cx={r.xb} cy={r.y} r={14} fill={P.accent_cool} />
                </g>
              ))}
            </g>
          </g>
        </g>

        {/* persistent anchor — screen-stable through the whole dive */}
        <g opacity={0.75}>
          <circle cx={CX} cy={CY} r={46} fill="none" stroke={P.ink} strokeWidth={2} strokeDasharray="6 8" />
          <line x1={CX - 62} y1={CY} x2={CX - 38} y2={CY} stroke={P.ink} strokeWidth={2} />
          <line x1={CX + 38} y1={CY} x2={CX + 62} y2={CY} stroke={P.ink} strokeWidth={2} />
        </g>

        {/* stage labels — slide transitions driven by S thresholds */}
        <g opacity={op0} transform={`translate(0 ${(1 - op0) * 20})`}>
          <text x={90} y={1700} fill={P.ink} fontFamily={FONT} fontWeight={700} fontSize={38} letterSpacing={3}>SURFACE — THE EYE</text>
          <text x={90} y={1744} fill={P.ink_dim} fontFamily={FONT} fontSize={26} letterSpacing={2}>a lens built for focus</text>
        </g>
        <g opacity={op1} transform={`translate(0 ${(1 - op1) * 20})`}>
          <text x={90} y={1700} fill={P.ink} fontFamily={FONT} fontWeight={700} fontSize={38} letterSpacing={3}>INSIDE — EPITHELIAL TISSUE</text>
          <text x={90} y={1744} fill={P.ink_dim} fontFamily={FONT} fontSize={26} letterSpacing={2}>cells locked edge to edge</text>
        </g>
        <g opacity={op2} transform={`translate(0 ${(1 - op2) * 20})`}>
          <text x={90} y={1700} fill={P.ink} fontFamily={FONT} fontWeight={700} fontSize={38} letterSpacing={3}>CORE — DNA HELIX</text>
          <text x={90} y={1744} fill={P.ink_dim} fontFamily={FONT} fontSize={26} letterSpacing={2}>two meters, coiled</text>
        </g>

        {/* integrated scale indicator */}
        <g opacity={0.85}>
          <text x={990} y={1700} textAnchor="end" fill={P.accent_warm} fontFamily={FONT} fontWeight={700} fontSize={64} letterSpacing={2}>
            ×{scaleText}
          </text>
          <text x={990} y={1740} textAnchor="end" fill={P.ink_dim} fontFamily={FONT} fontSize={24} letterSpacing={3}>
            MAGNIFICATION
          </text>
        </g>
      </svg>
    </AbsoluteFill>
  );
};

export default BenchC;
