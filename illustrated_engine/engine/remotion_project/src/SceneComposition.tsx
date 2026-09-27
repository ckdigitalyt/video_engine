import React from "react";
import { AbsoluteFill, Audio, staticFile, useCurrentFrame } from "remotion";

/**
 * V14 Stage 5 — generic scene renderer driven by compiled Scene IR props.
 * The Python adapter (engine/scene_renderer.py) compiles a validated
 * scene_spec.json (seconds domain) into these props (frames domain).
 * Deterministic: every random draw comes from seeded mulberry32 — no
 * Math.random, no wall clock. Grammar-specific payload coverage grows in
 * Stage 6; unhandled payloads warn once and render nothing.
 */

export interface CompiledCamKf {
  frame: number;
  scale: number;
  x: number;
  y: number;
  easing?: string;
}

export interface CompiledAnimKf {
  frame: number;
  value: number | [number, number];
  easing?: string;
}

export interface CompiledAnim {
  property: string; // "position" | "opacity" | "scale" | "rotation"
  keyframes: CompiledAnimKf[];
}

export interface CompiledLayer {
  id: string;
  type: string;
  semantic_role: string;
  source: string;
  position: [number, number];
  scale: number;
  rotation: number;
  opacity: number;
  z: number;
  depth: number;
  anchor: string;
  visibility: [number, number];
  payload: Record<string, any>;
  animations: CompiledAnim[];
}

export interface CompiledProps {
  specHash: string;
  width: number;
  height: number;
  fps: number;
  durationInFrames: number;
  seed: number;
  camera: {
    type: string;
    keyframes: CompiledCamKf[];
    apertures: string[];
    value_space: string;
  };
  layers: CompiledLayer[];
  palette: Record<string, string> | null;
}

// ---------- deterministic helpers ----------

export const DEFAULT_PAL = {
  bg_deep: "#0A1D33",
  bg_mid: "#12405C",
  accent_warm: "#F2A65A",
  accent_cool: "#3E7CB1",
  ink: "#E8EEF4",
  ink_dim: "#9FB3C8",
  line: "#2A4E6E",
  shadow: "#04101E",
};
type Pal = typeof DEFAULT_PAL;

const FONT = "Inter, 'Helvetica Neue', Arial, sans-serif";

const clamp01 = (x: number): number => Math.min(1, Math.max(0, x));

const EASINGS: Record<string, (t: number) => number> = {
  linear: (t) => t,
  ease_in_out_cubic: (t) =>
    t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2,
  ease_out_cubic: (t) => 1 - Math.pow(1 - t, 3),
  ease_in_cubic: (t) => t * t * t,
};

const easeOf = (name?: string): ((t: number) => number) =>
  EASINGS[name ?? "linear"] ?? EASINGS.linear;

export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashStr(s: string): number {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

interface CamState {
  scale: number;
  x: number;
  y: number;
}

const camOf = (k: CompiledCamKf): CamState => ({ scale: k.scale, x: k.x, y: k.y });

function evalCam(frame: number, kfs: CompiledCamKf[]): CamState {
  if (kfs.length === 0) return { scale: 1, x: 0, y: 0 };
  const first = kfs[0];
  const last = kfs[kfs.length - 1];
  if (frame <= first.frame) return camOf(first);
  if (frame >= last.frame) return camOf(last);
  for (let i = 0; i < kfs.length - 1; i++) {
    const a = kfs[i];
    const b = kfs[i + 1];
    if (frame >= a.frame && frame <= b.frame) {
      const span = b.frame - a.frame;
      const t = span <= 0 ? 1 : (frame - a.frame) / span;
      const e = easeOf(a.easing)(t);
      return {
        scale: a.scale + (b.scale - a.scale) * e,
        x: a.x + (b.x - a.x) * e,
        y: a.y + (b.y - a.y) * e,
      };
    }
  }
  return camOf(last);
}

const isNum = (v: number | [number, number]): v is number =>
  typeof v === "number";

function animScalar(
  anims: CompiledAnim[],
  property: string,
  frame: number
): number | null {
  const a = anims.find((x) => x.property === property);
  if (!a || a.keyframes.length === 0) return null;
  const kfs = a.keyframes;
  const last = kfs[kfs.length - 1];
  if (frame <= kfs[0].frame) return isNum(kfs[0].value) ? kfs[0].value : null;
  if (frame >= last.frame) return isNum(last.value) ? last.value : null;
  for (let i = 0; i < kfs.length - 1; i++) {
    const ka = kfs[i];
    const kb = kfs[i + 1];
    if (
      frame >= ka.frame &&
      frame <= kb.frame &&
      isNum(ka.value) &&
      isNum(kb.value)
    ) {
      const span = kb.frame - ka.frame;
      const t = span <= 0 ? 1 : (frame - ka.frame) / span;
      const e = easeOf(ka.easing)(t);
      return ka.value + (kb.value - ka.value) * e;
    }
  }
  return isNum(last.value) ? last.value : null;
}

const asVec = (v: number | [number, number]): [number, number] =>
  typeof v === "number" ? [v, v] : v;

function animVec(
  anims: CompiledAnim[],
  property: string,
  frame: number
): [number, number] | null {
  const a = anims.find((x) => x.property === property);
  if (!a || a.keyframes.length === 0) return null;
  const kfs = a.keyframes;
  const last = kfs[kfs.length - 1];
  if (frame <= kfs[0].frame) return asVec(kfs[0].value);
  if (frame >= last.frame) return asVec(last.value);
  for (let i = 0; i < kfs.length - 1; i++) {
    const ka = kfs[i];
    const kb = kfs[i + 1];
    if (frame >= ka.frame && frame <= kb.frame) {
      const va = asVec(ka.value);
      const vb = asVec(kb.value);
      const span = kb.frame - ka.frame;
      const t = span <= 0 ? 1 : (frame - ka.frame) / span;
      const e = easeOf(ka.easing)(t);
      return [va[0] + (vb[0] - va[0]) * e, va[1] + (vb[1] - va[1]) * e];
    }
  }
  return asVec(last.value);
}

// ---------- svg defs helpers ----------

function pushRadialGradient(
  defs: JSX.Element[],
  id: string,
  stops: string[],
  focus?: [number, number]
): void {
  const n = Math.max(1, stops.length - 1);
  defs.push(
    <radialGradient
      key={id}
      id={id}
      cx={`${((focus?.[0] ?? 0.4) * 100).toFixed(1)}%`}
      cy={`${((focus?.[1] ?? 0.35) * 100).toFixed(1)}%`}
      r="80%"
    >
      {stops.map((c, i) => (
        <stop
          key={i}
          offset={`${Math.round((i / n) * 100)}%`}
          stopColor={c}
        />
      ))}
    </radialGradient>
  );
}

function pushBlur(defs: JSX.Element[], id: string, std: number): void {
  defs.push(
    <filter key={id} id={id} x="-80%" y="-80%" width="260%" height="260%">
      <feGaussianBlur stdDeviation={std} />
    </filter>
  );
}

// ---------- layer body rendering ----------

interface Ctx {
  frame: number;
  cam: CamState;
  w: number;
  h: number;
  cx: number;
  cy: number;
  pal: Pal;
  fps: number;
  seed: number;
  v0: number;
  v1: number;
  defs: JSX.Element[];
}

const warned = new Set<string>();

function warnUnhandled(layer: CompiledLayer): void {
  if (warned.has(layer.id)) return;
  warned.add(layer.id);
  console.warn(
    `[SceneComposition] no renderer for layer ${layer.id} (source=${layer.source}, payload keys=${Object.keys(
      layer.payload ?? {}
    ).join(",")})`
  );
}

// ---------- generic primitive lists (grammar-emitted geometry) ----------

function renderPrimitives(pr: any, pal: Pal): JSX.Element {
  const out: JSX.Element[] = [];
  (pr.rects ?? []).forEach((r: any, i: number) =>
    out.push(
      <rect key={`r${i}`} x={r.x} y={r.y} width={r.w} height={r.h}
        fill={r.fill ?? pal.accent_cool} fillOpacity={r.fill_opacity ?? 0.85}
        stroke={r.stroke} strokeWidth={r.stroke_w ?? 2} rx={r.rx ?? 0}
        opacity={r.opacity ?? 1} />
    )
  );
  (pr.ellipses ?? []).forEach((e: any, i: number) =>
    out.push(
      <ellipse key={`e${i}`} cx={e.x} cy={e.y} rx={e.rx} ry={e.ry}
        fill={e.fill ?? pal.accent_cool} fillOpacity={e.fill_opacity ?? 0.85}
        stroke={e.stroke} strokeWidth={e.stroke_w ?? 2} opacity={e.opacity ?? 1}
        transform={e.rot ? `rotate(${e.rot} ${e.x} ${e.y})` : undefined} />
    )
  );
  (pr.circles ?? []).forEach((c: any, i: number) =>
    out.push(
      <circle key={`c${i}`} cx={c.x} cy={c.y} r={c.r}
        fill={c.fill ?? pal.accent_cool} fillOpacity={c.fill_opacity ?? 0.85}
        stroke={c.stroke} strokeWidth={c.stroke_w ?? 2} opacity={c.opacity ?? 1} />
    )
  );
  (pr.lines ?? []).forEach((l: any, i: number) =>
    out.push(
      <line key={`l${i}`} x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2}
        stroke={l.stroke ?? pal.ink} strokeWidth={l.width ?? 3}
        opacity={l.opacity ?? 1} strokeDasharray={l.dash} strokeLinecap="round" />
    )
  );
  (pr.paths ?? []).forEach((q: any, i: number) =>
    out.push(
      <path key={`p${i}`} d={q.d} fill={q.fill ?? "none"} fillOpacity={q.fill_opacity ?? 1}
        stroke={q.stroke} strokeWidth={q.width ?? 3} opacity={q.opacity ?? 1}
        strokeDasharray={q.dash} strokeLinecap="round" strokeLinejoin="round" />
    )
  );
  (pr.polylines ?? []).forEach((q: any, i: number) =>
    out.push(
      <polyline key={`pl${i}`} points={q.points} fill={q.fill ?? "none"}
        fillOpacity={q.fill_opacity ?? 1} stroke={q.stroke ?? pal.ink}
        strokeWidth={q.width ?? 4} opacity={q.opacity ?? 1}
        strokeLinecap="round" strokeLinejoin="round" />
    )
  );
  (pr.texts ?? []).forEach((t: any, i: number) =>
    out.push(
      <text key={`t${i}`} x={t.x} y={t.y} textAnchor={t.anchor ?? "middle"}
        fill={t.fill ?? pal.ink} fontFamily={FONT} fontWeight={t.weight ?? 700}
        fontSize={t.size ?? 40} letterSpacing={t.spacing ?? 0}
        opacity={t.opacity ?? 1}>
        {t.text}
      </text>
    )
  );
  return <g key="prims">{out}</g>;
}

function renderBody(layer: CompiledLayer, ctx: Ctx): JSX.Element | null {
  const p: any = layer.payload ?? {};
  const { pal, cx, cy, w, h } = ctx;
  const gid = `grad-${layer.id}`;
  const blid = `blur-${layer.id}`;

  if (p.primitives) {
    return renderPrimitives(p.primitives, pal);
  }

  // background / environment gradients
  if (layer.source === "generated_gradient" && p.kind === "radial" && !p.shape) {
    pushRadialGradient(ctx.defs, gid, p.stops ?? [pal.bg_mid, pal.bg_deep], p.focus);
    return <rect key="bg" width={w} height={h} fill={`url(#${gid})`} />;
  }
  if (layer.source === "generated_gradient" && p.shape === "circle") {
    pushRadialGradient(ctx.defs, gid, p.stops ?? [pal.accent_warm, pal.shadow], [0.4, 0.35]);
    return (
      <circle
        key="gc"
        cx={cx}
        cy={cy}
        r={p.r ?? 150}
        fill={`url(#${gid})`}
        stroke={p.stroke ?? pal.accent_warm}
        strokeWidth={2.5}
      />
    );
  }
  if (layer.source === "generated_shape" && p.shape === "circle") {
    return (
      <circle
        key="c"
        cx={cx}
        cy={cy}
        r={p.r ?? 200}
        fill={p.fill ?? pal.bg_mid}
        fillOpacity={p.fill_opacity ?? 0.9}
        stroke={p.stroke ?? pal.line}
        strokeWidth={p.stroke_w ?? 3}
      />
    );
  }
  if (layer.source === "generated_shape" && p.shape === "ellipse") {
    const rx = Array.isArray(p.r) ? p.r[0] : (p.rx ?? 300);
    const ry = Array.isArray(p.r) ? p.r[1] : (p.ry ?? 60);
    pushBlur(ctx.defs, blid, p.blur ?? 34);
    return (
      <ellipse
        key="e"
        cx={cx}
        cy={cy}
        rx={rx}
        ry={ry}
        fill={p.fill ?? pal.shadow}
        opacity={p.opacity ?? 0.5}
        filter={`url(#${blid})`}
      />
    );
  }
  if (layer.source === "generated_shape" && p.blobs) {
    const n = p.blobs ?? 3;
    const r = mulberry32(ctx.seed + hashStr(layer.id) + 3);
    const range = Array.isArray(p.opacity) ? p.opacity : [0.08, 0.16];
    pushBlur(ctx.defs, blid, p.blur ?? 34);
    const blobs = Array.from({ length: n }, () => ({
      x: 200 + r() * 700,
      y: 300 + r() * 1300,
      rx: 220 + r() * 200,
      ry: 90 + r() * 120,
      ph: r() * 6,
      op: range[0] + r() * (range[1] - range[0]),
    }));
    return (
      <g key="blobs">
        {blobs.map((b, i) => (
          <ellipse
            key={i}
            cx={b.x + 40 * Math.sin(ctx.frame / 60 + b.ph)}
            cy={b.y + 24 * Math.cos(ctx.frame / 80 + b.ph)}
            rx={b.rx}
            ry={b.ry}
            fill={pal.accent_cool}
            opacity={b.op}
            filter={`url(#${blid})`}
          />
        ))}
      </g>
    );
  }
  if (layer.source === "generated_shape" && p.arcs) {
    const n = p.arcs ?? 2;
    return (
      <g key="arcs">
        {Array.from({ length: n }, (_, i) => (
          <path
            key={i}
            d={`M -80 ${1560 + i * 140} Q 540 ${1420 + i * 160} 1160 ${1600 + i * 140}`}
            fill="none"
            stroke={pal.bg_deep}
            strokeWidth={90 - i * 30}
            strokeLinecap="round"
            opacity={(p.opacity ?? 0.5) * (1 - i * 0.3)}
          />
        ))}
      </g>
    );
  }
  if (layer.source === "procedural_svg" && p.squiggles) {
    const n = p.squiggles ?? 9;
    const r = mulberry32(ctx.seed + hashStr(layer.id) + 1);
    return (
      <g key="sq">
        {Array.from({ length: n }, (_, i) => {
          const a = (i / n) * Math.PI * 2 + r() * 0.6;
          const rad = 240 + r() * 110;
          const x = cx + Math.cos(a) * rad;
          const y = cy + Math.sin(a) * rad;
          const len = 60 + r() * 90;
          const rot = (a * 180) / Math.PI + r() * 50;
          const sw = 1.4 + r() * 1.2;
          return (
            <path
              key={i}
              d={`M ${x - len / 2} ${y} q ${len / 4} -14 ${len / 2} 0 t ${len / 4} 6`}
              fill="none"
              stroke={pal.ink_dim}
              strokeWidth={sw}
              opacity={0.28}
              strokeLinecap="round"
              transform={`rotate(${rot} ${x} ${y})`}
            />
          );
        })}
      </g>
    );
  }
  if (layer.source === "procedural_svg" && p.shape === "eye") {
    const irisR = p.iris_r ?? 210;
    const pupilR = p.pupil_r ?? 64;
    const nS = p.striations ?? 26;
    const r = mulberry32(ctx.seed + hashStr(layer.id) + 7);
    pushRadialGradient(ctx.defs, gid, [pal.accent_cool, pal.bg_mid, pal.bg_deep], [0.4, 0.35]);
    const striations = Array.from({ length: nS }, (_, i) => {
      const a = (i / nS) * Math.PI * 2 + r() * 0.15;
      return {
        x1: cx + Math.cos(a) * irisR * 0.55,
        y1: cy + Math.sin(a) * irisR * 0.55,
        x2: cx + Math.cos(a) * irisR * 0.95,
        y2: cy + Math.sin(a) * irisR * 0.95,
        o: 0.25 + r() * 0.3,
      };
    });
    return (
      <g key="eye">
        <ellipse cx={cx} cy={cy} rx={irisR * 1.55} ry={irisR * 1.05} fill={pal.ink} opacity={0.88} />
        <circle cx={cx} cy={cy} r={irisR} fill={`url(#${gid})`} />
        {striations.map((s, i) => (
          <line key={i} x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} stroke={pal.ink_dim} strokeWidth={2} opacity={s.o} />
        ))}
        <circle cx={cx} cy={cy} r={pupilR} fill="#04101E" />
        <circle cx={cx - pupilR * 0.4} cy={cy - pupilR * 0.4} r={pupilR * 0.18} fill={pal.ink} opacity={0.4} />
      </g>
    );
  }
  if (layer.source === "procedural_svg" && p.cells) {
    const n = p.cells ?? 12;
    const r = mulberry32(ctx.seed + hashStr(layer.id) + 11);
    const cols = Math.max(2, Math.ceil(Math.sqrt(n * (w / h))));
    const rows = Math.max(1, Math.ceil(n / cols));
    const cw = w / cols;
    const chh = h / rows;
    const cells = Array.from({ length: n }, (_, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      const x = col * cw + cw / 2 + (r() - 0.5) * cw * 0.25;
      const y = row * chh + chh / 2 + (r() - 0.5) * chh * 0.25;
      const rx = Math.min(cw, chh) * (0.36 + r() * 0.1);
      return { x, y, rx, ry: rx * (0.75 + r() * 0.3), rot: r() * 180 };
    });
    const junctions: JSX.Element[] = [];
    if (p.junctions) {
      for (let i = 0; i < n; i++) {
        const col = i % cols;
        const row = Math.floor(i / cols);
        if (col + 1 < cols && i + 1 < n) {
          junctions.push(
            <line key={`jh${i}`} x1={cells[i].x} y1={cells[i].y} x2={cells[i + 1].x} y2={cells[i + 1].y}
              stroke={pal.ink_dim} strokeWidth={2.5} opacity={0.3} />
          );
        }
        if (row + 1 < rows && i + cols < n) {
          junctions.push(
            <line key={`jv${i}`} x1={cells[i].x} y1={cells[i].y} x2={cells[i + cols].x} y2={cells[i + cols].y}
              stroke={pal.ink_dim} strokeWidth={2.5} opacity={0.3} />
          );
        }
      }
    }
    return (
      <g key="cells">
        {junctions}
        {cells.map((c, i) => (
          <g key={i}>
            <ellipse cx={c.x} cy={c.y} rx={c.rx} ry={c.ry} fill={pal.accent_cool} fillOpacity={0.18}
              stroke={pal.line} strokeWidth={2} transform={`rotate(${c.rot} ${c.x} ${c.y})`} />
            <ellipse cx={c.x} cy={c.y} rx={c.rx * 0.22} ry={c.ry * 0.22} fill={pal.ink_dim} opacity={0.35} />
          </g>
        ))}
      </g>
    );
  }
  if (layer.source === "procedural_svg" && p.helix) {
    const amp = p.helix.amplitude ?? 150;
    const period = p.helix.period ?? 110;
    const len = p.helix.length ?? 1400;
    const rungsEvery = p.helix.rungs_every ?? 100;
    const strand = (phase: number): string => {
      const pts: string[] = [];
      for (let x = -len / 2; x <= len / 2; x += 6) {
        pts.push(`${x.toFixed(1)},${(amp * Math.sin((2 * Math.PI * x) / period + phase)).toFixed(1)}`);
      }
      return pts.join(" ");
    };
    const rungs: JSX.Element[] = [];
    for (let x = -len / 2; x <= len / 2; x += rungsEvery) {
      const yA = amp * Math.sin((2 * Math.PI * x) / period);
      const yB = amp * Math.sin((2 * Math.PI * x) / period + Math.PI);
      rungs.push(
        <line key={x} x1={x} y1={yA} x2={x} y2={yB} stroke={pal.accent_warm} strokeWidth={3.5}
          opacity={0.8} strokeLinecap="round" />
      );
    }
    return (
      <g key="helix" transform={`translate(${cx} ${cy})`}>
        {rungs}
        <polyline points={strand(0)} fill="none" stroke={pal.ink} strokeWidth={7} strokeLinecap="round" />
        <polyline points={strand(Math.PI)} fill="none" stroke={pal.ink_dim} strokeWidth={5}
          strokeLinecap="round" opacity={0.8} />
      </g>
    );
  }
  if (layer.source === "vector" && p.leader_from) {
    const lf = p.leader_from;
    const el = p.elbow ?? lf;
    const ta = p.text_at ?? lf;
    const prog = easeOf("ease_out_cubic")(clamp01((ctx.frame - ctx.v0) / Math.max(1, ctx.fps)));
    return (
      <g key="ann">
        <circle cx={lf[0]} cy={lf[1]} r={7} fill={pal.accent_warm} opacity={prog} />
        <path
          d={`M ${lf[0]} ${lf[1]} L ${el[0]} ${el[1]} L ${ta[0]} ${ta[1]}`}
          fill="none"
          stroke={pal.ink}
          strokeWidth={2.5}
          strokeLinecap="round"
          pathLength={1}
          strokeDasharray={1}
          strokeDashoffset={1 - prog}
        />
        <g opacity={prog}>
          {p.title ? (
            <text x={ta[0]} y={ta[1] - 12} textAnchor={p.text_anchor ?? "end"} fill={pal.ink} fontFamily={FONT}
              fontWeight={700} fontSize={40} letterSpacing={3}>{p.title}</text>
          ) : null}
          {p.sub ? (
            <text x={ta[0]} y={ta[1] + 36} textAnchor={p.text_anchor ?? "end"} fill={pal.ink_dim} fontFamily={FONT}
              fontSize={28} letterSpacing={2}>{p.sub}</text>
          ) : null}
        </g>
      </g>
    );
  }
  if (layer.source === "vector" && p.shape === "dashed_ring") {
    return (
      <circle key="ring" cx={cx} cy={cy} r={p.screen_r ?? 46} fill="none"
        stroke={pal.ink_dim} strokeWidth={2.5} strokeDasharray="6 9" />
    );
  }
  if (layer.source === "vector" && p.format) {
    const pos = p.position ?? [cx, cy];
    return (
      <text key="fmt" x={pos[0]} y={pos[1]} textAnchor={p.anchor ?? "end"} fill={pal.ink}
        fontFamily={FONT} fontWeight={700} fontSize={p.size ?? 46}>
        {String(p.format).replace("{S}", ctx.cam.scale.toFixed(1))}
      </text>
    );
  }
  if (layer.source === "vector" && p.stages) {
    const stages: any[] = p.stages ?? [];
    const cur =
      stages.find((s) => s.until_scale == null || ctx.cam.scale < s.until_scale) ??
      stages[stages.length - 1];
    if (!cur) return null;
    const pos = p.position ?? [90, 1700];
    return (
      <g key="stage">
        <text x={pos[0]} y={pos[1]} textAnchor={p.anchor ?? "start"} fill={pal.ink}
          fontFamily={FONT} fontWeight={700} fontSize={40} letterSpacing={3}>{cur.title}</text>
        <text x={pos[0]} y={pos[1] + 48} textAnchor={p.anchor ?? "start"} fill={pal.ink_dim}
          fontFamily={FONT} fontSize={28} letterSpacing={2}>{cur.sub}</text>
      </g>
    );
  }
  if ((layer.source === "vector" || layer.source === "text") && (p.text || p.title)) {
    const pos = p.position ?? [cx, cy];
    return (
      <text key="text" x={pos[0]} y={pos[1]} textAnchor={p.anchor ?? "middle"}
        fill={p.fill ?? pal.ink} fontFamily={FONT} fontWeight={p.bold === false ? 400 : 700}
        fontSize={p.size ?? 44} letterSpacing={p.spacing ?? 0}>
        {p.text ?? p.title}
      </text>
    );
  }
  if (layer.source === "ai_image" || layer.source === "raster") {
    if (!p.path) return null;
    return (
      <image key="img" href={staticFile(p.path)} x={0} y={0} width={w} height={h}
        preserveAspectRatio="xMidYMid slice" />
    );
  }
  if (layer.type === "background" || layer.type === "environment") {
    return <rect key="bgf" width={w} height={h} fill={pal.bg_deep} />;
  }
  return null;
}

// ---------- main composition ----------

export const EMPTY_PROPS: CompiledProps = {
  specHash: "0000000000000000",
  width: 1080,
  height: 1920,
  fps: 30,
  durationInFrames: 2,
  seed: 1,
  camera: {
    type: "static",
    keyframes: [
      { frame: 0, scale: 1, x: 0, y: 0, easing: "linear" },
      { frame: 2, scale: 1, x: 0, y: 0, easing: "linear" },
    ],
    apertures: [],
    value_space: "linear_scale",
  },
  layers: [
    {
      id: "bg",
      type: "background",
      semantic_role: "world_ground",
      source: "generated_gradient",
      position: [0, 0],
      scale: 1,
      rotation: 0,
      opacity: 1,
      z: 0,
      depth: 0,
      anchor: "center",
      visibility: [0, 2],
      payload: { kind: "radial", stops: ["#12405C", "#0A1D33"], focus: [0.5, 0.42] },
      animations: [],
    },
  ],
  palette: null,
};

const SceneComposition: React.FC<CompiledProps> = (props) => {
  const frame = useCurrentFrame();
  const { width, height, fps } = props;
  const cam = evalCam(frame, props.camera.keyframes);
  const cx = width / 2;
  const cy = height / 2;
  const pal: Pal = { ...DEFAULT_PAL, ...(props.palette ?? {}) };

  const sorted = [...props.layers].sort((a, b) => a.z - b.z);
  const defs: JSX.Element[] = [];
  const body: JSX.Element[] = [];
  const audio: JSX.Element[] = [];
  let aperture: string | null = null;

  for (const layer of sorted) {
    if (layer.source === "audio") {
      const src = layer.payload?.path;
      if (src) {
        audio.push(
          <Audio key={layer.id} src={staticFile(src)} volume={layer.payload?.volume ?? 1} />
        );
      }
      continue;
    }
    if (layer.type === "mask") {
      const worldR = layer.payload?.world_r ?? 100;
      const grows = layer.payload?.grows_with_camera !== false;
      const rr = grows ? worldR * cam.scale : worldR;
      defs.push(
        <clipPath key={`clip-${layer.id}`} id={`clip-${layer.id}`}>
          <circle cx={cx} cy={cy} r={Math.max(0, rr)} />
        </clipPath>
      );
      aperture = layer.id;
      continue;
    }
    const [v0, v1] = layer.visibility;
    if (frame < v0 || frame > v1) continue;
    const screenSpace = layer.type === "semantic_annotation" || layer.type === "text";
    const ctx: Ctx = { frame, cam, w: width, h: height, cx, cy, pal, fps, seed: props.seed, v0, v1, defs };
    const inner = renderBody(layer, ctx);
    if (!inner) {
      warnUnhandled(layer);
      continue;
    }

    const hasOpacityAnim = layer.animations.some((a) => a.property === "opacity");
    const fade =
      v0 > 0 && !hasOpacityAnim
        ? easeOf("ease_out_cubic")(clamp01((frame - v0) / (0.4 * fps)))
        : 1;
    const aop = animScalar(layer.animations, "opacity", frame);
    const opacity = layer.opacity * (aop ?? 1) * fade;

    const ls = typeof layer.payload?.local_scale === "number" ? layer.payload.local_scale : null;
    const pf = ls != null ? 1 : layer.payload?.grows_with_camera ? 1 : 0.3 + 0.7 * layer.depth;
    const S = ls != null ? cam.scale * ls : 1 + (cam.scale - 1) * pf;
    const camT =
      `translate(${cx} ${cy}) scale(${S}) translate(${-cx} ${-cy}) ` +
      `translate(${(-cam.x * pf).toFixed(2)} ${(-cam.y * pf).toFixed(2)})`;

    const dpos = animVec(layer.animations, "position", frame);
    const ascale = animScalar(layer.animations, "scale", frame);
    const arot = animScalar(layer.animations, "rotation", frame);
    const layerT =
      `translate(${layer.position[0]} ${layer.position[1]})` +
      (layer.rotation ? ` rotate(${layer.rotation})` : "") +
      (layer.scale !== 1 ? ` scale(${layer.scale})` : "");
    const animT =
      (dpos ? `translate(${dpos[0].toFixed(2)} ${dpos[1].toFixed(2)})` : "") +
      (ascale != null ? ` scale(${ascale})` : "") +
      (arot != null ? ` rotate(${arot})` : "");

    body.push(
      <g
        key={layer.id}
        opacity={opacity}
        clipPath={!screenSpace && aperture ? `url(#clip-${aperture})` : undefined}
      >
        {screenSpace ? (
          <g transform={layerT}>
            <g transform={animT}>{inner}</g>
          </g>
        ) : (
          <g transform={camT}>
            <g transform={layerT}>
              <g transform={animT}>{inner}</g>
            </g>
          </g>
        )}
      </g>
    );
  }

  return (
    <AbsoluteFill style={{ backgroundColor: pal.shadow }}>
      {audio}
      <svg width="100%" height="100%" viewBox={`0 0 ${width} ${height}`}>
        <defs>{defs}</defs>
        {body}
      </svg>
    </AbsoluteFill>
  );
};

export default SceneComposition;
