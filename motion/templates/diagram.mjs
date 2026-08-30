// templates/diagram.mjs — labeled boxes connected by animated arrows.
export function render(ctx, { W, H }, props, t, P, h) {
  const nodes = Array.isArray(props.nodes) ? props.nodes : [];
  const edges = Array.isArray(props.edges) ? props.edges : [];
  const pos = new Map();

  nodes.forEach((node, i) => {
    const n = Math.max(nodes.length, 1);
    const appear = h.easeOutCubic(h.window01(t, (0.7 * i) / n, (0.7 * i) / n + 0.22));
    if (appear <= 0) return;
    const layout = String(props.layout ?? "row");
    let x, y;
    if (layout === "row") {
      x = (W * (i + 1)) / (n + 1);
      y = H / 2;
    } else { // column
      x = W / 2;
      y = (H * (i + 1)) / (n + 1);
    }
    pos.set(i, { x, y, appear });
    const bw = Number(props.box_w ?? 300), bh = Number(props.box_h ?? 120);
    ctx.save();
    ctx.globalAlpha = appear;
    ctx.translate(x, y);
    ctx.scale(0.8 + 0.2 * appear, 0.8 + 0.2 * appear);
    ctx.fillStyle = P.background;
    ctx.strokeStyle = i === 0 ? P.accent : P.secondary;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.roundRect(-bw / 2, -bh / 2, bw, bh, 16);
    ctx.fill();
    ctx.stroke();
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = h.font(30, 600);
    ctx.fillStyle = P.primary;
    const lines = h.wrapText(ctx, String(node.label ?? node.id ?? ""), bw - 24);
    lines.slice(0, 3).forEach((line, li) => {
      ctx.fillText(line, 0, (li - (lines.length - 1) / 2) * 36);
    });
    ctx.restore();
  });

  edges.forEach(([from, to], i) => {
    const a = pos.get(from), b = pos.get(to);
    if (!a || !b) return;
    const appear = h.window01(t, 0.25 + 0.5 * (i / Math.max(edges.length, 1)),
                              0.5 + 0.5 * (i / Math.max(edges.length, 1)));
    if (appear <= 0) return;
    ctx.save();
    ctx.globalAlpha = h.easeOutCubic(appear);
    ctx.strokeStyle = P.accent;
    ctx.lineWidth = 3;
    // Edge grows from a toward b.
    const ex = a.x + (b.x - a.x) * appear;
    const ey = a.y + (b.y - a.y) * appear;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(ex, ey);
    ctx.stroke();
    if (appear > 0.95) {
      ctx.fillStyle = P.accent;
      ctx.beginPath();
      ctx.arc(b.x, b.y, 6, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  });
}
export default render;
