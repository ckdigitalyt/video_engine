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
      // body + long THIN neck + small head + tail + column legs, facing left
      // (r5 audit misread the thick-necked mound as a whale silhouette)
      ctx.moveTo(cx - 0.72 * s, baseY);            // tail tip (low)
      ctx.quadraticCurveTo(cx - 0.5 * s, baseY - 0.2 * s, cx - 0.3 * s, baseY - 0.32 * s);  // tail→back
      ctx.quadraticCurveTo(cx - 0.1 * s, baseY - 0.44 * s, cx + 0.08 * s, baseY - 0.46 * s); // back
      ctx.quadraticCurveTo(cx + 0.18 * s, baseY - 0.56 * s, cx + 0.24 * s, baseY - 0.8 * s);  // neck back edge
      ctx.quadraticCurveTo(cx + 0.27 * s, baseY - 0.98 * s, cx + 0.31 * s, baseY - 1.0 * s);  // head top
      ctx.quadraticCurveTo(cx + 0.37 * s, baseY - 0.98 * s, cx + 0.35 * s, baseY - 0.9 * s);  // snout
      ctx.quadraticCurveTo(cx + 0.29 * s, baseY - 0.72 * s, cx + 0.25 * s, baseY - 0.54 * s); // neck front (thin)
      ctx.quadraticCurveTo(cx + 0.22 * s, baseY - 0.42 * s, cx + 0.32 * s, baseY - 0.3 * s);  // chest
      ctx.lineTo(cx + 0.32 * s, baseY);                // front leg (front edge)
      ctx.lineTo(cx + 0.18 * s, baseY);                // front leg (back edge)
      ctx.lineTo(cx + 0.16 * s, baseY - 0.22 * s);     // belly arch
      ctx.lineTo(cx - 0.02 * s, baseY - 0.24 * s);
      ctx.lineTo(cx - 0.04 * s, baseY);                // hind leg (front edge)
      ctx.lineTo(cx - 0.2 * s, baseY);                 // hind leg (back edge)
      ctx.lineTo(cx - 0.22 * s, baseY - 0.18 * s);     // under-tail
      ctx.quadraticCurveTo(cx - 0.45 * s, baseY - 0.14 * s, cx - 0.72 * s, baseY); // tail underside
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
  // v4.1.1: the corner tag is redundant when it duplicates the side's own
  // title (r5 audit: "BEFORE appears twice" on the S15 wipe card).
  const beforeTag = String(props.before_label ?? "BEFORE");
  if (beforeTag.toLowerCase() !== String(before.title ?? "").toLowerCase()) {
    ctx.fillText(beforeTag, 24, 48);
  }
  if (revealP > 0.15) {
    const afterTag = String(props.after_label ?? "AFTER");
    if (afterTag.toLowerCase() !== String(after.title ?? "").toLowerCase()) {
      ctx.textAlign = "right";
      ctx.fillText(afterTag, W - 24, 48);
    }
  }
  ctx.restore();
}
export default render;
