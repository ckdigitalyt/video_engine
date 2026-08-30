// templates/timeline.mjs — horizontal axis with sequential event markers.
export function render(ctx, { W, H }, props, t, P, h) {
  const title = String(props.title ?? "");
  const events = Array.isArray(props.events) ? props.events : [];
  const n = Math.max(events.length, 1);
  const y = H * 0.55;
  const x0 = W * 0.12, x1 = W * 0.88;

  if (title) {
    ctx.save();
    ctx.textAlign = "center";
    ctx.font = h.font(52, 700);
    ctx.fillStyle = P.primary;
    ctx.fillText(title, W / 2, H * 0.18);
    ctx.restore();
  }

  // Axis grows in.
  const axisP = h.easeOutCubic(h.window01(t, 0, 0.25));
  ctx.strokeStyle = P.secondary;
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(x0, y);
  ctx.lineTo(x0 + (x1 - x0) * axisP, y);
  ctx.stroke();

  events.forEach((ev, i) => {
    const appear = h.window01(t, 0.2 + (0.7 * i) / n, 0.35 + (0.7 * i) / n);
    if (appear <= 0) return;
    const x = x0 + ((x1 - x0) * (i + 0.5)) / n;
    const a = h.easeOutCubic(appear);
    ctx.save();
    ctx.globalAlpha = a;
    // marker
    ctx.fillStyle = i === events.length - 1 ? P.highlight : P.accent;
    ctx.beginPath();
    ctx.arc(x, y, 12 * a, 0, Math.PI * 2);
    ctx.fill();
    // label above or below (alternate to avoid collisions)
    const above = i % 2 === 0;
    ctx.font = h.font(34, 600);
    ctx.fillStyle = P.primary;
    ctx.textAlign = "center";
    const label = String(ev.label ?? "");
    const date = String(ev.date ?? "");
    ctx.fillText(label, x, above ? y - 70 : y + 50);
    ctx.font = h.font(28, 400);
    ctx.fillStyle = P.secondary;
    ctx.fillText(date, x, above ? y - 30 : y + 92);
    ctx.restore();
  });
}
export default render;
