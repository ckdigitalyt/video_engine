// templates/comparison.mjs — two labeled columns with items appearing.
export function render(ctx, { W, H }, props, t, P, h) {
  const left = props.left ?? {};
  const right = props.right ?? {};
  const cols = [
    { ...left, x: W * 0.27, color: props.left_color ?? P.accent },
    { ...right, x: W * 0.73, color: props.right_color ?? P.highlight },
  ];
  const items = Math.max(
    (left.items ?? []).length, (right.items ?? []).length, 1);

  // Divider.
  ctx.save();
  ctx.strokeStyle = P.secondary;
  ctx.globalAlpha = 0.4;
  ctx.setLineDash([8, 10]);
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(W / 2, H * 0.22);
  ctx.lineTo(W / 2, H * 0.88);
  ctx.stroke();
  ctx.restore();

  cols.forEach((col, ci) => {
    const headP = h.easeOutCubic(h.window01(t, 0, 0.25));
    ctx.save();
    ctx.globalAlpha = headP;
    ctx.textAlign = "center";
    ctx.font = h.font(48, 700);
    ctx.fillStyle = col.color;
    ctx.fillText(String(col.title ?? ""), col.x, H * 0.18);
    ctx.restore();

    (col.items ?? []).forEach((item, i) => {
      const appear = h.easeOutCubic(
        h.window01(t, 0.25 + (0.65 * (i + ci * 0.3)) / items,
                   0.45 + (0.65 * (i + ci * 0.3)) / items));
      if (appear <= 0) return;
      const y = H * 0.32 + i * 78;
      ctx.save();
      ctx.globalAlpha = appear;
      ctx.textAlign = "center";
      ctx.font = h.font(34, 400);
      ctx.fillStyle = P.primary;
      ctx.translate(col.x + (1 - appear) * 40 * (ci === 0 ? -1 : 1), y);
      ctx.fillText(String(item), 0, 0);
      ctx.restore();
    });
  });
}
export default render;
