import React from "react";
import {
  continueRender,
  delayRender,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { Caption, createTikTokStyleCaptions } from "@remotion/captions";

/**
 * V16 WP5 — Remotion-native captions, replacing the Python `chunk_png` +
 * ffmpeg-overlay pass (engine/captions.py) for the parity-tested subset of
 * its behaviour: one line of words per cue, the currently spoken word
 * highlighted, on a rounded dark scrim, below the card.
 *
 * Grouping uses the real @remotion/captions API (`createTikTokStyleCaptions`)
 * on a flat per-word timeline computed by Python (engine.v16_compose,
 * from the exact windows the live pass already burns) — not a
 * reimplementation of the cue/chunk logic. `combineWithinMs` sits strictly
 * between the live pipeline's 0ms intra-cue gap and its >=50ms
 * (engine.captions.STATE_GAP) inter-cue gap, so the regrouped pages equal
 * the Python cues exactly (verified in bench/ab/wp5_parity.py).
 */

export interface CaptionWord {
  text: string;
  startMs: number;
  endMs: number;
}

export interface CaptionsProps {
  track: CaptionWord[];
  combineWithinMs: number;
  bandTop: number;
  textColor: string;
  activeColor: string;
}

const FRAME_W = 1080;
const BAND_H = 192;
const MARGIN_X = 56;
const BASE_SIZE = 64;
const MIN_SIZE = 30;
const FONT_FAMILY = "JadeCaption";

function useCaptionFont(): void {
  const [handle] = React.useState(() => delayRender("jade-caption-font"));
  React.useEffect(() => {
    new FontFace(FONT_FAMILY, `url(${staticFile("fonts/caption.ttf")})`)
      .load()
      .then((f) => {
        (document as any).fonts.add(f);
      })
      .catch((e) => console.warn(`[Captions] font load failed: ${e}`))
      .finally(() => continueRender(handle));
  }, [handle]);
}

let _ctx: CanvasRenderingContext2D | null = null;
function measureCtx(): CanvasRenderingContext2D {
  if (!_ctx) {
    const c = document.createElement("canvas");
    _ctx = c.getContext("2d") as CanvasRenderingContext2D;
  }
  return _ctx;
}

/** Mirrors engine.captions._chunk_font: step the size down by 4 until the
 * single line of upper-cased words fits FRAME_W - 2*MARGIN_X, floor 30. */
function fitSize(words: string[]): { size: number; width: number; gap: number } {
  const ctx = measureCtx();
  let size = BASE_SIZE;
  for (;;) {
    ctx.font = `900 ${size}px ${FONT_FAMILY}`;
    const gap = ctx.measureText(" ").width;
    const width =
      words.reduce((acc, w) => acc + ctx.measureText(w).width, 0) +
      gap * (words.length - 1);
    if (width <= FRAME_W - 2 * MARGIN_X || size <= MIN_SIZE) {
      return { size, width, gap };
    }
    size -= 4;
  }
}

export const Captions: React.FC<CaptionsProps> = ({
  track,
  combineWithinMs,
  bandTop,
  textColor,
  activeColor,
}) => {
  useCaptionFont();
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const tMs = (frame / fps) * 1000;

  const captions: Caption[] = React.useMemo(
    () =>
      track.map((w) => ({
        text: w.text,
        startMs: w.startMs,
        endMs: w.endMs,
        timestampMs: null,
        confidence: null,
      })),
    [track]
  );
  const { pages } = React.useMemo(
    () =>
      createTikTokStyleCaptions({
        captions,
        combineTokensWithinMilliseconds: combineWithinMs,
      }),
    [captions, combineWithinMs]
  );

  const page = pages.find(
    (p) => tMs >= p.startMs && tMs < p.startMs + p.durationMs
  );
  if (!page || page.tokens.length === 0) return null;

  const words = page.tokens.map((t) => t.text.toUpperCase());
  const activeIdx = page.tokens.findIndex(
    (t) => tMs >= t.fromMs && tMs < t.toMs
  );
  const { size, width, gap } = fitSize(words);
  const asc = size * 0.8;
  const desc = size * 0.2;
  const lineH = asc + desc;
  const y0 = BAND_H / 2 - lineH / 2;
  const x0 = (FRAME_W - width) / 2;

  const ctx = measureCtx();
  ctx.font = `900 ${size}px ${FONT_FAMILY}`;
  let x = x0;
  const boxes = words.map((w) => {
    const ww = ctx.measureText(w).width;
    const box = { x, w: ww };
    x += ww + gap;
    return box;
  });
  const padX = 26;
  const padY = 14;
  const bx0 = x0 - padX;
  const bx1 = x0 + width + padX;
  const by0 = y0 - padY;
  const by1 = y0 + lineH + padY;

  return (
    <svg
      width={FRAME_W}
      height={BAND_H}
      viewBox={`0 0 ${FRAME_W} ${BAND_H}`}
      style={{ position: "absolute", left: 0, top: bandTop }}
    >
      <rect
        x={bx0}
        y={by0}
        width={bx1 - bx0}
        height={by1 - by0}
        rx={18}
        fill="#000000"
        fillOpacity={105 / 255}
      />
      {boxes.map((b, i) => {
        const active = i === activeIdx;
        const fill = active ? activeColor : textColor;
        const shadowOpacity = active ? 160 / 255 : 140 / 255;
        return (
          <g key={i}>
            <text
              x={b.x + 2}
              y={y0 + asc + 4}
              fontFamily={FONT_FAMILY}
              fontWeight={900}
              fontSize={size}
              fill="#000000"
              fillOpacity={shadowOpacity}
            >
              {words[i]}
            </text>
            <text
              x={b.x}
              y={y0 + asc}
              fontFamily={FONT_FAMILY}
              fontWeight={900}
              fontSize={size}
              fill={fill}
              fillOpacity={active ? 1 : 235 / 255}
            >
              {words[i]}
            </text>
            {active ? (
              <rect
                x={b.x + 2}
                y={y0 + lineH + 6}
                width={b.w - 4}
                height={6}
                rx={3}
                fill={activeColor}
                fillOpacity={200 / 255}
              />
            ) : null}
          </g>
        );
      })}
    </svg>
  );
};

export default Captions;
