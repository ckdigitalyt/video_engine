// templates/reveal.mjs — image or text revealed by an expanding mask.
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);

export function render(ctx, { W, H }, props, t, P, h) {
  const mode = String(props.mode ?? "circle"); // circle | wipe | bars
  const rp = h.easeInOutCubic(h.window01(t, 0.05, 0.7));

  const drawContent = () => {
    if (props.image) {
      const img = props.__img; // preloaded by the runner
      if (img) {
        const s = Math.max(W / img.width, H / img.height);
        ctx.drawImage(img, (W - img.width * s) / 2, (H - img.height * s) / 2,
                      img.width * s, img.height * s);
      }
    }
    if (props.title) {
      ctx.save();
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.font = h.font(props.image ? 54 : 92, 800);
      ctx.fillStyle = props.image ? "#ffffff" : P.primary;
      ctx.shadowColor = "rgba(0,0,0,0.7)";
      ctx.shadowBlur = props.image ? 14 : 0;
      const lines = h.wrapText(ctx, String(props.title), W * 0.8);
      lines.slice(0, 3).forEach((line, i) => {
        ctx.fillText(line, W / 2, H / 2 + (i - (lines.length - 1) / 2) * 100);
      });
      ctx.restore();
    }
  };

  ctx.save();
  if (mode === "circle") {
    ctx.beginPath();
    ctx.arc(W / 2, H / 2, Math.hypot(W, H) / 2 * rp, 0, Math.PI * 2);
    ctx.clip();
    drawContent();
  } else if (mode === "wipe") {
    ctx.beginPath();
    ctx.rect(0, 0, W * rp, H);
    ctx.clip();
    drawContent();
  } else { // bars
    const bars = 8;
    for (let i = 0; i < bars; i++) {
      const bp = h.easeOutCubic(h.clamp01(rp * bars - i));
      ctx.save();
      ctx.beginPath();
      ctx.rect((W / bars) * i, 0, W / bars, H * bp);
      ctx.clip();
      drawContent();
      ctx.restore();
    }
  }
  ctx.restore();

  // Final settle flash (subtle).
  if (rp >= 1) {
    const settle = h.window01(t, 0.7, 0.85);
    ctx.save();
    ctx.globalAlpha = 0.12 * (1 - settle);
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, W, H);
    ctx.restore();
  }
}
export default render;
