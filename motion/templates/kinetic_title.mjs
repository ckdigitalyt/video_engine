// templates/kinetic_title.mjs — title slides/typewriters in with subtitle.
export function render(ctx, { W, H }, props, t, P, h) {
  const title = String(props.title ?? "");
  const subtitle = String(props.subtitle ?? "");
  const mode = String(props.mode ?? "slide"); // slide | typewriter | scale
  const lines = h.wrapText(ctx, title, W * 0.8);
  const inP = h.easeOutCubic(h.window01(t, 0, 0.35));

  ctx.save();
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  let y = H / 2 - ((lines.length - 1) * 60) / 2 - (subtitle ? 30 : 0);
  ctx.font = h.font(84, 700);
  ctx.fillStyle = P.primary;
  for (const [i, line] of lines.entries()) {
    let text = line;
    let alpha = inP;
    let dx = 0;
    if (mode === "typewriter") {
      const chars = Math.round(line.length * h.window01(t, 0, 0.5 - i * 0.05));
      text = line.slice(0, chars);
    } else if (mode === "scale") {
      ctx.save();
      const s = 0.6 + 0.4 * inP;
      ctx.translate(W / 2, y);
      ctx.scale(s, s);
      ctx.globalAlpha = inP;
      ctx.fillStyle = i === 0 ? P.accent : P.primary;
      ctx.fillText(line, 0, 0);
      ctx.restore();
      y += 120;
      continue;
    } else {
      dx = (1 - inP) * 120;
    }
    ctx.globalAlpha = alpha;
    ctx.fillText(text, W / 2 + dx, y + i * 120);
    y += 0;
  }
  if (subtitle) {
    const subP = h.easeOutCubic(h.window01(t, 0.4, 0.7));
    ctx.globalAlpha = subP;
    ctx.font = h.font(44, 400);
    ctx.fillStyle = P.secondary;
    ctx.fillText(subtitle, W / 2, H / 2 + 130);
  }
  ctx.restore();
}
export default render;
