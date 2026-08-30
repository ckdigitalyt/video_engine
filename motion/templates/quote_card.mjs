// templates/quote_card.mjs — quote fades/rises in with attribution.
export function render(ctx, { W, H }, props, t, P, h) {
  const quote = String(props.quote ?? "");
  const attribution = String(props.attribution ?? "");

  ctx.save();
  // Oversized decorative quote mark.
  const markP = h.easeOutCubic(h.window01(t, 0, 0.2));
  ctx.globalAlpha = 0.25 * markP;
  ctx.font = h.font(260, 800);
  ctx.fillStyle = P.accent;
  ctx.textAlign = "left";
  ctx.fillText("\u201C", W * 0.1, H * 0.34);
  ctx.restore();

  ctx.save();
  ctx.textAlign = "center";
  ctx.font = h.font(52, 400, "serif");
  ctx.fillStyle = P.primary;
  const lines = h.wrapText(ctx, quote, W * 0.72);
  const qp = h.window01(t, 0.1, 0.6);
  lines.forEach((line, i) => {
    const lp = h.easeOutCubic(h.window01(qp * lines.length, i, i + 1));
    ctx.globalAlpha = lp;
    ctx.fillText(line, W / 2, H / 2 - (lines.length - 1) * 40 + i * 80 + (1 - lp) * 24);
  });
  ctx.restore();

  if (attribution) {
    const ap = h.easeOutCubic(h.window01(t, 0.65, 0.85));
    ctx.save();
    ctx.globalAlpha = ap;
    ctx.textAlign = "center";
    ctx.font = h.font(34, 600);
    ctx.fillStyle = P.secondary;
    ctx.fillText(`— ${attribution}`, W / 2, H * 0.82);
    ctx.restore();
  }
}
export default render;
