// templates/diagram.mjs — labeled boxes connected by animated arrows.
export function render(ctx, { W, H }, props, t, P, h) {
  const nodes = Array.isArray(props.nodes) ? props.nodes : [];
  const edges = Array.isArray(props.edges) ? props.edges : [];
  const pos = new Map();

  // tree layout: roots left, descendants spread by depth (branching reads
  // as branching — the r3 "row" layout turned a fork into a chain).
  const depth = new Map();
  const kids = new Map();
  if (edges.length && String(props.layout ?? "") === "tree") {
    nodes.forEach((_, i) => depth.set(i, 0));
    edges.forEach(([f, t]) => {
      if (!kids.has(f)) kids.set(f, []);
      kids.get(f).push(t);
    });
    let changed = true;
    let guard = 0;
    while (changed && guard++ < 8) {
      changed = false;
      edges.forEach(([f, t]) => {
        if ((depth.get(t) ?? 0) < (depth.get(f) ?? 0) + 1) {
          depth.set(t, (depth.get(f) ?? 0) + 1);
          changed = true;
        }
      });
    }
  }
  const byDepth = new Map();
  nodes.forEach((_, i) => {
    const d = depth.get(i) ?? 0;
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d).push(i);
  });
  const posFor = (i, n) => {
    if (String(props.layout ?? "row") === "tree" && edges.length) {
      const d = depth.get(i) ?? 0;
      const col = byDepth.get(d) ?? [i];
      const k = col.indexOf(i);
      return {
        x: W * 0.2 + d * W * 0.3,
        y: H * (0.5 + (col.length > 1
          ? (k - (col.length - 1) / 2) * 0.32 : 0)),
      };
    }
    if (String(props.layout ?? "row") === "row") {
      return { x: (W * (i + 1)) / (n + 1), y: H / 2 };
    }
    return { x: W / 2, y: (H * (i + 1)) / (n + 1) };
  };

  nodes.forEach((node, i) => {
    const n = Math.max(nodes.length, 1);
    const appear = h.easeOutCubic(h.window01(t, (0.7 * i) / n, (0.7 * i) / n + 0.22));
    if (appear <= 0) return;
    const layout = String(props.layout ?? "row");
    const { x, y } = posFor(i, n);
    pos.set(i, { x, y, appear });
    const bw = Number(props.box_w ?? 300), bh = Number(props.box_h ?? 120);
    // §19 branch-fate styling: a node marked "dead" in props.fate fades
    // out (the extinction edge), "surviving" carries the highlight.
    const fate = (props.fate ?? {})[String(i)];
    ctx.save();
    ctx.globalAlpha = appear * (fate === "dead" ? 0.45 : 1);
    ctx.translate(x, y);
    ctx.scale(0.8 + 0.2 * appear, 0.8 + 0.2 * appear);
    ctx.fillStyle = P.background;
    ctx.strokeStyle = fate === "surviving" ? P.highlight
      : (fate === "dead" ? P.secondary : (i === 0 ? P.accent : P.secondary));
    ctx.lineWidth = fate === "surviving" ? 5 : 3;
    if (fate === "dead") ctx.setLineDash([10, 8]);
    ctx.beginPath();
    ctx.roundRect(-bw / 2, -bh / 2, bw, bh, 16);
    ctx.fill();
    ctx.stroke();
    ctx.setLineDash([]);
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
