/* The azulejo rim, drawn on a canvas inside the map's own surface (above the map, below the zoom buttons and popup).
   The SDK draws "markers along a line" as a texture stretched along the line, which shears square tiles into
   parallelograms on a curve and makes them overlap or gap depending on zoom. Here every tile is placed and rotated
   exactly, and the number of tiles is recomputed every frame so the ring always closes without a seam. */
import * as reactiveUtils from "@arcgis/core/core/reactiveUtils.js";

const COBALT = "#1e4bb8", CREAM = "#fbf7f0", TERRA = "#c2541f";
const T = 22;                 // tile size, px
const ROPE = 6.5, TILES = 25; // distances from the sea edge, px: rope moulding, tile centres
const BAND = TILES + T / 2 + 8;
const S = 4;                  // sprite oversampling for crisp tiles

function ellipse(ctx, cx, cy, rx, ry, rot) { ctx.beginPath(); ctx.ellipse(cx, cy, rx, ry, rot, 0, 2 * Math.PI); }

/** a pair of tiles, 40 × 20 units: A = cobalt ground with a cream quatrefoil, B = cream ground with a cobalt star */
function pairSprite() {
  const cv = document.createElement("canvas");
  cv.width = 40 * S; cv.height = 20 * S;
  const c = cv.getContext("2d");
  c.scale(S, S); c.translate(20, 10);
  c.fillStyle = COBALT; c.fillRect(-20, -10, 20, 20);
  c.fillStyle = CREAM;
  for (let k = 0; k < 4; k++) { const a = k * Math.PI / 2; ellipse(c, -10 + Math.cos(a) * 4.6, Math.sin(a) * 4.6, 3.6, 1.9, a); c.fill(); }
  c.fillStyle = TERRA; ellipse(c, -10, 0, 1.7, 1.7, 0); c.fill();
  c.fillStyle = CREAM; c.fillRect(0, -10, 20, 20);
  c.fillStyle = COBALT; c.beginPath();
  for (let k = 0; k < 8; k++) { const a = k / 8 * 2 * Math.PI + Math.PI / 4, r = k % 2 ? 2.4 : 7.6; c.lineTo(10 + Math.cos(a) * r, Math.sin(a) * r); }
  c.closePath(); c.fill();
  c.fillStyle = CREAM; ellipse(c, 10, 0, 1.4, 1.4, 0); c.fill();
  c.fillStyle = "rgba(30,75,184,0.78)";       // quarter circles in the corners: they join into circles across tiles
  for (const [x, y] of [[0, -10], [20, -10], [20, 10], [0, 10]]) {
    const a0 = Math.atan2(-y, 10 - x) - Math.PI / 4;
    c.beginPath(); c.moveTo(x, y); c.arc(x, y, 4.2, a0, a0 + Math.PI / 2); c.closePath(); c.fill();
  }
  c.strokeStyle = "rgba(251,247,240,0.9)"; c.lineWidth = 0.5;   // a hairline of grout between tiles
  c.strokeRect(-20, -10, 20, 20); c.strokeRect(0, -10, 20, 20);
  return cv;
}

/** one strand of the twisted rope */
function strandSprite() {
  const cv = document.createElement("canvas");
  cv.width = cv.height = 12 * S;
  const c = cv.getContext("2d");
  c.scale(S, S); c.translate(6, 6);
  ellipse(c, 0, 0, 4.8, 1.7, Math.PI / 4);
  c.fillStyle = COBALT; c.fill(); c.strokeStyle = CREAM; c.lineWidth = 0.7; c.stroke();
  return cv;
}

export function canvasRim(view, center, plateR) {
  const cv = document.createElement("canvas");
  Object.assign(cv.style, { position: "absolute", inset: "0", width: "100%", height: "100%", pointerEvents: "none" });
  view.surface.appendChild(cv);
  const ctx = cv.getContext("2d");
  const pair = pairSprite(), strand = strandSprite();

  function ring(cx, cy, r, width, color) {
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2 * Math.PI); ctx.lineWidth = width; ctx.strokeStyle = color; ctx.stroke();
  }

  function draw() {
    const w = view.width, h = view.height, dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const p = view.toScreen(center);
    if (!p || !view.resolution) return;
    const cx = p.x, cy = p.y, r = plateR / view.resolution;
    // nothing to draw when the whole band is off-screen (zoomed in, or panned away)
    const nx = Math.max(0, Math.min(w, cx)), ny = Math.max(0, Math.min(h, cy));
    const near = Math.hypot(cx - nx, cy - ny), far = Math.max(Math.hypot(cx, cy), Math.hypot(cx - w, cy), Math.hypot(cx, cy - h), Math.hypot(cx - w, cy - h));
    if (near > r + BAND + 2 || far < r - 2) return;
    const visible = (x, y, m) => x > -m && x < w + m && y > -m && y < h + m;

    ring(cx, cy, r + BAND / 2, BAND, CREAM);                     // the plate's glazed body
    ring(cx, cy, r, 1.6, COBALT);                                // sea edge
    ring(cx, cy, r + 11.5, 1.2, COBALT);                         // inner line of the moulding
    ring(cx, cy, r + TILES - T / 2 - 1, 1.2, COBALT);            // tile band lines
    ring(cx, cy, r + TILES + T / 2 + 1, 1.2, COBALT);

    const rr = r + ROPE, nRope = Math.max(12, Math.round(2 * Math.PI * rr / 3.6));
    for (let i = 0; i < nRope; i++) {
      const a = i / nRope * 2 * Math.PI, x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr;
      if (!visible(x, y, 8)) continue;
      ctx.save(); ctx.translate(x, y); ctx.rotate(a + Math.PI / 2); ctx.drawImage(strand, -3.5, -3.5, 7, 7); ctx.restore();
    }

    const rt = r + TILES, nPairs = Math.max(6, Math.round(2 * Math.PI * rt / (2 * T))), pw = 2 * Math.PI * rt / nPairs;
    for (let i = 0; i < nPairs; i++) {
      const a = (i + 0.5) / nPairs * 2 * Math.PI - Math.PI / 2, x = cx + Math.cos(a) * rt, y = cy + Math.sin(a) * rt;
      if (!visible(x, y, pw)) continue;
      ctx.save(); ctx.translate(x, y); ctx.rotate(a + Math.PI / 2); ctx.drawImage(pair, -pw / 2, -T / 2, pw, T); ctx.restore();
    }
  }

  // redraw whenever the camera moves (every frame of a pan or zoom animation) or the view is resized
  const handle = reactiveUtils.watch(() => [view.extent, view.width, view.height], draw, { initial: true });
  return { draw, remove: () => { handle.remove(); cv.remove(); } };
}
