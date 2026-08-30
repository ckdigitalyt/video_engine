// templates/before_after.mjs — split-screen wipe between two states.
export function render(ctx, { W, H }, props, t, P, h) {
  const before = props.before ?? {};
  const after = props.after ?? {};
  const revealP = h.window01(t, 0.15, 0.75); // 0..1 how much "after" covers

  // BEFORE side fills whole frame, AFTER side wipes in from the right.
  const drawSide = (side, x, w, color) => {
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, 0, w, H);
    ctx.clip();
    ctx.fillStyle = color;
    ctx.fillRect(x, 0, w, H);
    if (side.title) {
      ctx.textAlign = "center";
      ctx.font = h.font(72, 800);
      ctx.fillStyle = P.primary;
      ctx.fillText(String(side.title), x + w / 2, H / 2 - 20);
    }
    if (side.caption) {
      ctx.font = h.font(36, 400);
      ctx.fillStyle = P.secondary;
      const lines = h.wrapText(ctx, String(side.caption), w * 0.8);
      lines.slice(0, 2).forEach((line, i) => {
        ctx.fillText(line, x + w / 2, H / 2 + 50 + i * 46);
      });
    }
    ctx.restore();
  };

  drawSide(before, 0, W, props.before_color ?? "#3a2f4a");
  // After panel: width grows from 0 to half, then to full at the end.
  const afterW = W * revealP;
  if (afterW > 0) {
    drawSide(after, W - afterW, afterW, props.after_color ?? "#1d4e3f");
  }

  // Divider line + labels.
  ctx.save();
  ctx.strokeStyle = P.primary;
  ctx.lineWidth = 4;
  ctx.beginPath();
  ctx.moveTo(W - afterW, 0);
  ctx.lineTo(W - afterW, H);
  ctx.stroke();
  ctx.font = h.font(30, 700);
  ctx.textAlign = "left";
  ctx.fillStyle = P.secondary;
  ctx.globalAlpha = 0.9;
  ctx.fillText(String(props.before_label ?? "BEFORE"), 24, 48);
  if (revealP > 0.15) {
    ctx.textAlign = "right";
    ctx.fillText(String(props.after_label ?? "AFTER"), W - 24, 48);
  }
  ctx.restore();
}
export default render;
