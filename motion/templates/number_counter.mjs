// templates/number_counter.mjs — big number counting with easing + label.
export function render(ctx, { W, H }, props, t, P, h) {
  const from = Number(props.from ?? 0);
  const to = Number(props.to ?? 100);
  const label = String(props.label ?? "");
  const prefix = String(props.prefix ?? "");
  const suffix = String(props.suffix ?? "");
  const bigP = h.window01(t, 0.05, 0.85);

  ctx.save();
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const scaleIn = h.easeOutCubic(h.window01(t, 0, 0.15));
  ctx.translate(W / 2, H / 2 - 40);
  ctx.scale(0.85 + 0.15 * scaleIn, 0.85 + 0.15 * scaleIn);
  ctx.font = h.font(150, 800);
  ctx.fillStyle = P.accent;
  const val = from + (to - from) * h.easeOutCubic(bigP);
  const text = Math.abs(to - from) >= 10 || Number.isInteger(from + to)
    ? Math.round(val).toLocaleString("en-US")
    : val.toFixed(1);
  ctx.fillText(`${prefix}${text}${suffix}`, 0, 0);
  ctx.restore();

  if (label) {
    const lp = h.easeOutCubic(h.window01(t, 0.25, 0.5));
    ctx.save();
    ctx.globalAlpha = lp;
    ctx.textAlign = "center";
    ctx.font = h.font(44, 500);
    ctx.fillStyle = P.primary;
    const lines = h.wrapText(ctx, label, W * 0.7);
    lines.slice(0, 2).forEach((line, i) => {
      ctx.fillText(line, W / 2, H * 0.72 + i * 54);
    });
    ctx.restore();
  }
}
export default render;
