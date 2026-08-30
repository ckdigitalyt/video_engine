// templates/map_zoom.mjs — abstract map plate with camera push to a marker.
// Accepts an optional props.map_image (path) drawn as the base plate; a
// deterministic procedural "landmass" pattern is drawn when absent.
// (props.__map_img is preloaded by render.mjs before the first frame.)
export function render(ctx, { W, H }, props, t, P, h) {
  const zoomP = h.easeInOutCubic(t);
  const target = props.target ?? { x: 0.62, y: 0.45 };
  const label = String(props.label ?? "");
  const zoom = 1 + 1.4 * zoomP;

  ctx.save();
  ctx.translate(W / 2, H / 2);
  ctx.scale(zoom, zoom);
  ctx.translate(-target.x * W, -target.y * H);

  if (props.map_image) {
    // Runner preloads the image into props.__map_img (loadImage is async).
    const img = props.__map_img;
    if (img) ctx.drawImage(img, 0, 0, W, H);
  } else {
    // Procedural abstract map: soft blobs on deep blue.
    ctx.fillStyle = "#0d1b2e";
    ctx.fillRect(0, 0, W, H);
    const blobs = props.blobs ?? [
      [0.25, 0.3, 0.22], [0.6, 0.25, 0.16], [0.75, 0.6, 0.2],
      [0.35, 0.7, 0.17], [0.5, 0.5, 0.12],
    ];
    ctx.fillStyle = "#1c3a57";
    for (const [bx, by, br] of blobs) {
      ctx.beginPath();
      ctx.ellipse(bx * W, by * H, br * W, br * W * 0.72, 0, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  // Grid lines for cartographic feel.
  ctx.strokeStyle = "rgba(255,255,255,0.06)";
  ctx.lineWidth = 1.5;
  for (let gx = 0; gx <= W; gx += W / 12) {
    ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, H); ctx.stroke();
  }
  for (let gy = 0; gy <= H; gy += H / 8) {
    ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(W, gy); ctx.stroke();
  }

  // Target marker pulses in once zoom settles.
  const markerP = h.easeOutCubic(h.window01(t, 0.55, 0.8));
  if (markerP > 0) {
    const pulse = 1 + 0.15 * Math.sin(t * Math.PI * 6);
    ctx.strokeStyle = P.highlight;
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.arc(target.x * W, target.y * H, 26 * pulse * markerP, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = P.highlight;
    ctx.beginPath();
    ctx.arc(target.x * W, target.y * H, 8 * markerP, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();

  if (label) {
    const lp = h.easeOutCubic(h.window01(t, 0.7, 0.9));
    ctx.save();
    ctx.globalAlpha = lp;
    ctx.textAlign = "center";
    ctx.font = h.font(46, 700);
    ctx.fillStyle = P.primary;
    ctx.fillText(label, W / 2, H * 0.9);
    ctx.restore();
  }
}
export default render;
