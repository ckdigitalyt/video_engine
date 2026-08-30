// templates/infographic.mjs — labeled stat bars animating to their values.
export function render(ctx, { W, H }, props, t, P, h) {
  const title = String(props.title ?? "");
  const rows = Array.isArray(props.rows) ? props.rows : [];
  const n = Math.max(rows.length, 1);
  const top = H * 0.28;
  const barH = Math.min(52, (H * 0.5) / n - 18);
  const labelW = W * 0.26;
  const barX = W * 0.30;
  const barMaxW = W * 0.55;

  if (title) {
    ctx.save();
    ctx.textAlign = "left";
    ctx.font = h.font(50, 700);
    ctx.fillStyle = P.primary;
    ctx.fillText(title, W * 0.08, H * 0.16);
    ctx.restore();
  }

  rows.forEach((row, i) => {
    const appear = h.easeOutCubic(h.window01(t, (0.75 * i) / n, (0.75 * i) / n + 0.25));
    if (appear <= 0) return;
    const y = top + (i * (barH + 22));
    const value = Number(row.value ?? 0);
    const max = Number(props.max ?? Math.max(...rows.map(r => Number(r.value ?? 0)), 1));
    const w = barMaxW * Math.min(Math.abs(value) / max, 1) * appear;

    ctx.save();
    ctx.globalAlpha = appear;
    ctx.textAlign = "right";
    ctx.font = h.font(30, 500);
    ctx.fillStyle = P.secondary;
    ctx.fillText(String(row.label ?? ""), labelW - 16, y + barH * 0.7);
    ctx.fillStyle = i === 0 ? P.highlight : P.accent;
    ctx.globalAlpha = appear * 0.9;
    ctx.fillRect(barX, y, w, barH);
    ctx.globalAlpha = appear;
    ctx.textAlign = "left";
    ctx.font = h.font(30, 700);
    ctx.fillStyle = P.primary;
    ctx.fillText(String(row.display ?? row.value ?? ""), barX + w + 12, y + barH * 0.7);
    ctx.restore();
  });
}
export default render;
