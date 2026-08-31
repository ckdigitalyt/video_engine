// templates/before_after.mjs — split-screen wipe between two states.
export function render(ctx, { W, H }, props, t, P, h) {
  const before = props.before ?? {};
  const after = props.after ?? {};
  const revealP = h.window01(t, 0.15, 0.75); // 0..1 how much "after" covers

  // A flat color fill reads as an empty plate (r3 QA: "just a flat green
  // panel, subject missing") — shade the side and draw the size-comparison
  // figures the shot's claim is about (§24: show the claim, don't label it).
  const shadeSide = (x, w, color) => {
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, h.lighten(color, 0.08));
    g.addColorStop(1, h.darken(color, 0.12));
    ctx.fillStyle = g;
    ctx.fillRect(x, 0, w, H);
  };

  // Simple readable creature silhouettes (scale = fraction of panel height).
  const drawCreature = (cx, baseY, height, color, kind) => {
    const s = height; // overall bounding height
    ctx.save();
    ctx.fillStyle = color;
    ctx.beginPath();
    if (kind === "sauropod") {
      // body + long neck + tail + legs, facing left
      ctx.moveTo(cx - 0.55 * s, baseY);            // tail tip (low)
      ctx.quadraticCurveTo(cx - 0.75 * s, baseY - 0.35 * s, cx - 0.35 * s, baseY - 0.42 * s);
      ctx.quadraticCurveTo(cx - 0.1 * s, baseY - 0.5 * s, cx + 0.02 * s, baseY - 0.62 * s); // back→neck
      ctx.quadraticCurveTo(cx + 0.16 * s, baseY - 0.95 * s, cx + 0.24 * s, baseY - 1.0 * s); // neck up
      ctx.quadraticCurveTo(cx + 0.3 * s, baseY - 1.02 * s, cx + 0.3 * s, baseY - 0.94 * s);  // head
      ctx.quadraticCurveTo(cx + 0.22 * s, baseY - 0.72 * s, cx + 0.12 * s, baseY - 0.5 * s); // neck front
      ctx.quadraticCurveTo(cx + 0.28 * s, baseY - 0.42 * s, cx + 0.42 * s, baseY - 0.3 * s); // chest→hindleg
      ctx.quadraticCurveTo(cx + 0.5 * s, baseY - 0.2 * s, cx + 0.52 * s, baseY);             // rear
      ctx.lineTo(cx + 0.34 * s, baseY);
      ctx.quadraticCurveTo(cx + 0.1 * s, baseY - 0.12 * s, cx - 0.2 * s, baseY);
      ctx.closePath();
      ctx.fill();
    } else {
      // small generic mammal: rounded body + head + tail
      ctx.moveTo(cx - 0.5 * s, baseY);
      ctx.quadraticCurveTo(cx - 0.2 * s, baseY - 0.9 * s, cx + 0.25 * s, baseY - 0.75 * s);
      ctx.quadraticCurveTo(cx + 0.55 * s, baseY - 0.6 * s, cx + 0.5 * s, baseY);
      ctx.closePath();
      ctx.fill();
    }
    ctx.restore();
  };

  // BEFORE side fills whole frame, AFTER side wipes in from the right.
  const drawSide = (side, x, w, color) => {
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, 0, w, H);
    ctx.clip();
    shadeSide(x, w, color);
    const figure = side.figure ?? null;
    if (figure && typeof figure === "object") {
      const hFrac = Math.min(Math.max(Number(figure.height_frac ?? 0.5), 0.05), 0.82);
      const fh = H * hFrac;
      drawCreature(x + w * Number(figure.x ?? 0.5), H * 0.88, fh,
                   figure.color ?? "rgba(0,0,0,0.55)",
                   String(figure.kind ?? "mammal"));
    }
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
