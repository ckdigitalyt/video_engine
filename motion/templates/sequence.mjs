// sequence.mjs — composition runner: partitions the clip across sub-template
// segments. props.segments = [{template, props}, ...]; each gets an equal
// (or duration-weighted) slice of the timeline.
import { TEMPLATES } from "./index.mjs";

export default function render(ctx, size, props, t, P, h) {
  const segments = Array.isArray(props.segments) ? props.segments : [];
  if (!segments.length) return;
  const n = segments.length;
  const idx = Math.min(Math.floor(t * n), n - 1);
  const local = t * n - idx;
  const seg = segments[idx];
  const tpl = TEMPLATES[seg.template];
  if (!tpl) return;
  tpl(ctx, size, seg.props ?? {}, local, P, h);
  // Segment boundary flash (pattern interrupt).
  if (idx > 0 && local < 0.05) {
    ctx.save();
    ctx.globalAlpha = 0.15 * (1 - local / 0.05);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, size.W, size.H);
    ctx.restore();
  }
}
