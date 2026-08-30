// templates/callout.mjs — central keyword with radiating callout labels.
export function render(ctx, { W, H }, props, t, P, h) {
  const keyword = String(props.keyword ?? "");
  const callouts = Array.isArray(props.callouts) ? props.callouts : [];
  const n = Math.max(callouts.length, 1);

  // Central node.
  const cp = h.easeOutCubic(h.window01(t, 0, 0.3));
  ctx.save();
  ctx.translate(W / 2, H / 2);
  ctx.scale(0.7 + 0.3 * cp, 0.7 + 0.3 * cp);
  ctx.globalAlpha = cp;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.font = h.font(64, 800);
  ctx.fillStyle = P.highlight;
  ctx.fillText(keyword, 0, 0);
  ctx.strokeStyle = P.highlight;
  ctx.lineWidth = 4;
  const pad = 40;
  const tw = ctx.measureText(keyword).width;
  ctx.beginPath();
  ctx.roundRect(-tw / 2 - pad, -52, tw + pad * 2, 104, 20);
  ctx.stroke();
  ctx.restore();

  callouts.forEach((c, i) => {
    const appear = h.window01(t, 0.3 + (0.6 * i) / n, 0.5 + (0.6 * i) / n);
    if (appear <= 0) return;
    const a = h.easeOutCubic(appear);
    // Distribute callouts on a circle around the center.
    const angle = -Math.PI / 2 + (2 * Math.PI * i) / n + (n === 2 ? Math.PI / 6 : 0);
    const R = Math.min(W, H) * 0.33;
    const x = W / 2 + Math.cos(angle) * R * 1.4;
    const y = H / 2 + Math.sin(angle) * R;
    ctx.save();
    ctx.globalAlpha = a;
    ctx.strokeStyle = P.secondary;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(W / 2, H / 2);
    ctx.lineTo(W / 2 + (x - W / 2) * a, H / 2 + (y - H / 2) * a);
    ctx.stroke();
    ctx.textAlign = "center";
    ctx.font = h.font(32, 500);
    ctx.fillStyle = P.primary;
    ctx.fillText(String(c.text ?? ""), x, y);
    ctx.restore();
  });
}
export default render;
