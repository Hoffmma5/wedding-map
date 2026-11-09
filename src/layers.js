/* LAYERS: client-side FeatureLayers (renderers, labels, popups, legend), client-side ImageryTileLayers
   (shaded relief, ocean currents with the FlowRenderer) and GraphicsLayers for the plate and animation. */
import FeatureLayer from "@arcgis/core/layers/FeatureLayer.js";
import GraphicsLayer from "@arcgis/core/layers/GraphicsLayer.js";
import ImageryTileLayer from "@arcgis/core/layers/ImageryTileLayer.js";
import PixelBlock from "@arcgis/core/layers/support/PixelBlock.js";
import MediaLayer from "@arcgis/core/layers/MediaLayer.js";
import ImageElement from "@arcgis/core/layers/support/ImageElement.js";
import ExtentAndRotationGeoreference from "@arcgis/core/layers/support/ExtentAndRotationGeoreference.js";
import Extent from "@arcgis/core/geometry/Extent.js";
import Graphic from "@arcgis/core/Graphic.js";
import Polyline from "@arcgis/core/geometry/Polyline.js";
import Polygon from "@arcgis/core/geometry/Polygon.js";
import { SR, project, geo, PLATE_R } from "./projection.js";
import { SIDES } from "./config.js";

export const ring = (r, n = 360) => Array.from({ length: n + 1 }, (_, i) => [Math.cos(i / n * 2 * Math.PI) * r, Math.sin(i / n * 2 * Math.PI) * r]);
const fmt = n => Math.round(n).toLocaleString("en-GB").replace(/,/g, " ");
// RSVP text will come from guests (Survey123), so never inject it as raw HTML
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const COBALT = [30, 75, 184, 255], CREAM = [251, 247, 240, 255], SEA = [223, 232, 242, 255], BG = [239, 231, 218, 255];
const fields = (...f) => [{ name: "oid", type: "oid" }, ...f.map(([name, type]) => ({ name, type }))];
const clientLayer = (o) => new FeatureLayer({ objectIdField: "oid", spatialReference: SR, legendEnabled: false, popupEnabled: false, ...o });
const cim = symbol => ({ type: "cim", data: { type: "CIMSymbolReference", symbol } });
const fill = color => ({ type: "CIMPolygonSymbol", symbolLayers: [{ type: "CIMSolidFill", enable: true, color }] });
const stroke = (width, color, extra = {}) => ({ type: "CIMSolidStroke", enable: true, width, color, capStyle: "Round", joinStyle: "Round", ...extra });
const projLine = flat => { const o = []; for (let k = 0; k < flat.length; k += 2) o.push(project(flat[k], flat[k + 1])); return o; };
const mg = (geometry, symbol) => ({ type: "CIMMarkerGraphic", geometry, symbol });

/* ------------------------------------------------------------------ the plate */
const plateCircle = () => new Polyline({ paths: [ring(PLATE_R)], spatialReference: SR });

export function seaLayer() {
  const layer = new GraphicsLayer({ title: "Sea" });
  layer.add(new Graphic({ geometry: new Polygon({ rings: [ring(PLATE_R)], spatialReference: SR }), symbol: cim(fill(SEA)) }));
  return layer;
}

/** Everything outside the plate is painted over with the background, so nothing can spill past the rim. */
export function maskLayer() {
  const layer = new GraphicsLayer({ title: "Mask" });
  const big = 4 * PLATE_R;
  layer.add(new Graphic({
    geometry: new Polygon({ rings: [[[-big, -big], [-big, big], [big, big], [big, -big], [-big, -big]], ring(PLATE_R)], spatialReference: SR }),   // CCW inner ring = hole
    symbol: cim(fill(BG)) }));
  return layer;
}

const flower = Array.from({ length: 33 }, (_, i) => { const a = i / 32 * 2 * Math.PI, r = 3 + 2 * Math.abs(Math.cos(2 * a)); return [Math.cos(a) * r, Math.sin(a) * r]; });

/** The original, simple rim: a cream band with cobalt flowers. */
/*  (The "tiles" rim is drawn on a canvas by src/rim.js.) */
export function rimLayer() {
  const layer = new GraphicsLayer({ title: "Rim" });
  const layers = [
    { type: "CIMVectorMarker", enable: true, anchorPointUnits: "Relative", size: 9, frame: { xmin: -5, ymin: -5, xmax: 5, ymax: 5 },
      markerGraphics: [mg({ rings: [flower] }, fill(COBALT))],
      markerPlacement: { type: "CIMMarkerPlacementAlongLineSameSize", placementTemplate: [16], angleToLine: true, offset: -9 } },
    stroke(2, COBALT),
    stroke(24, CREAM, { effects: [{ type: "CIMGeometricEffectOffset", method: "Rounded", offset: -12, option: "Fast" }] }),
  ];
  layer.add(new Graphic({ geometry: plateCircle(), symbol: cim({ type: "CIMLineSymbol", symbolLayers: layers }) }));
  layer.maxScale = 9_000_000;   // closer in the rim is off-screen anyway
  return layer;
}

/* ------------------------------------------------------------------ vector layers */
export function graticuleLayer(world) {
  return clientLayer({ title: "Graticule", geometryType: "polyline", fields: fields(),
    source: world.grat.map((p, i) => new Graphic({ geometry: new Polyline({ paths: [p.map(([lon, lat]) => project(lon, lat))], spatialReference: SR }), attributes: { oid: i + 1 } })),
    renderer: { type: "simple", symbol: { type: "simple-line", color: [30, 75, 184, 0.10], width: 0.6 } } });
}

const landSource = (world) => world.countries.map(c => ({ rings: c.r.map(projLine), name: c.n }))
  .map((c, i) => new Graphic({ geometry: new Polygon({ rings: c.rings, spatialReference: SR }), attributes: { oid: i + 1, name: c.name } }));

// The dissolved, hand-inked coastline (scripts/world.py), not the countries: no strokes wasted on borders under land.
// Each entry is [exterior, holes…]; holes (inland seas cut off at this scale) must stay holes, or the ink floods them.
const coastSource = world => world.coast.map((rings, i) => new Graphic({ geometry: new Polygon({ rings: rings.map(projLine), spatialReference: SR }), attributes: { oid: i + 1 } }));

// Coastal water lines: stacked strokes drawn *under* the land
export function rippleLayer(world, rings = [3, 7.5, 12]) {
  return clientLayer({ title: "Coastal water lines", geometryType: "polygon", fields: fields(), source: coastSource(world),
    renderer: { type: "simple", symbol: cim({ type: "CIMPolygonSymbol",
      symbolLayers: rings.flatMap((d, k) => [
        { type: "CIMSolidStroke", enable: true, width: 2 * d - 0.8, color: SEA, joinStyle: "Round" },
        { type: "CIMSolidStroke", enable: true, width: 2 * d + 0.8, color: [30, 75, 184, Math.round(255 * 0.16 * (1 - k / 4))], joinStyle: "Round" },
      ]) }) } });
}

/** The inked coast: outline + fill, above the water lines and below the land. The land covers it except where the
    hand-drawn coast strays out to sea, and those wedges read as thicker ink. It has to be a layer of its own: within
    one symbol the SDK paints fills before strokes, so the water lines' wide strokes would cover the wedges. */
export function inkLayer(world, color) {
  // the coastline as a stroke only (half of it hidden by the land), plus the precomputed wedges outside the land:
  // no land-sized fill, so nothing large can flash through while the land's tiles are still being drawn
  const lines = coastSource(world).map(g => { g.attributes.kind = "line"; return g; });
  const wedges = (world.wedges ?? []).map(rings => new Graphic({ geometry: new Polygon({ rings: rings.map(projLine), spatialReference: SR }), attributes: { kind: "wedge" } }));
  const source = [...lines, ...wedges].map((g, i) => { g.attributes.oid = i + 1; return g; });
  return clientLayer({ title: "Coast ink", geometryType: "polygon", fields: fields(["kind", "string"]), source,
    renderer: { type: "unique-value", field: "kind", uniqueValueInfos: [
      { value: "line", symbol: cim({ type: "CIMPolygonSymbol", symbolLayers: [{ type: "CIMSolidStroke", enable: true, width: 1.8, color, joinStyle: "Round" }] }) },
      { value: "wedge", symbol: cim({ type: "CIMPolygonSymbol", symbolLayers: [{ type: "CIMSolidFill", enable: true, color }] }) },
    ] } });
}

export const LAND_STYLE = {
  // shadow = layer effect (an extra render pass; only the original keeps it), coast = inked coastline from the ripple layer
  sage:    { fill: "#c9d2ad", portugal: "#e3a57c", border: "#f4eee3", borderW: 0.7, shadow: "drop-shadow(1px, 2px, 0px rgba(96,110,70,0.35))" },
  apricot: { fill: "#f7e3cc", portugal: "#eeb48c", border: "#fbf7f0", borderW: 0.8, coast: [194, 84, 31, 120], relief: 0.5 },
  relief:  { fill: "#cfd6b6", portugal: "#e6ab84", border: "#f4eee3", borderW: 0.7, coast: [30, 75, 184, 90], relief: 0.55 },
  azulejo: { fill: "#fbf7f0", portugal: "#f3d3bd", border: "rgba(30,75,184,0.5)", borderW: 0.5, coast: [30, 75, 184, 210], relief: 0.7 },
};
export function landLayer(world, kind) {
  const s = LAND_STYLE[kind];
  const sym = color => ({ type: "simple-fill", color, outline: { color: s.border, width: s.borderW } });
  return clientLayer({ title: "Countries", geometryType: "polygon", fields: fields(["name", "string"]), source: landSource(world),
    ...(s.shadow ? { effect: s.shadow } : {}),
    renderer: { type: "unique-value", field: "name", defaultSymbol: sym(s.fill), uniqueValueInfos: [{ value: "Portugal", symbol: sym(s.portugal) }] } });
}

/** Contour lines (lon/lat from scripts/terrain.py): bathymetry in the sea, elevation on land. */
export function contourLayer(contours, which) {
  const src = [];
  for (const { z, l } of contours[which]) for (const flat of l) src.push(new Graphic({
    geometry: new Polyline({ paths: [projLine(flat)], spatialReference: SR }), attributes: { oid: src.length + 1, z } }));
  const sea = which === "sea";
  return clientLayer({ title: sea ? "Depth lines" : "Elevation lines", geometryType: "polyline", fields: fields(["z", "integer"]), source: src,
    copyright: "ETOPO1, NOAA NCEI",
    renderer: { type: "simple", symbol: { type: "simple-line", color: [30, 75, 184, 0.3], width: 0.6 },
      visualVariables: sea
        ? [{ type: "opacity", field: "z", stops: [{ value: -5000, opacity: 0.55 }, { value: -200, opacity: 0.22 }] },
           { type: "size", field: "z", stops: [{ value: -5000, size: 0.9 }, { value: -200, size: 0.5 }] }]
        : [{ type: "opacity", field: "z", stops: [{ value: 300, opacity: 0.35 }, { value: 4500, opacity: 0.8 }] },
           { type: "size", field: "z", stops: [{ value: 300, size: 0.45 }, { value: 4500, size: 0.8 }] }] } });
}

// Ocean waves: a little hand-drawn "~" as a CIM vector marker. With #cim in the URL they animate natively (CIM symbol animations).
const wavePath = Array.from({ length: 13 }, (_, i) => [i / 12 * 20, 3 + Math.sin(i / 12 * Math.PI * 2) * 2.4]);
const waveSym = (anim) => cim({
  type: "CIMPointSymbol",
  ...(anim ? { animations: [
    { type: "CIMSymbolAnimationOffset", offsetX: 4, offsetY: 1, animatedSymbolProperties: { playAnimation: true, repeatType: "Oscillate", easing: "EaseInOut", duration: 3.2, randomizeStartTime: true } },
    { type: "CIMSymbolAnimationTransparency", toTransparency: 85, animatedSymbolProperties: { playAnimation: true, repeatType: "Oscillate", easing: "EaseInOut", duration: 4.1, randomizeStartTime: true } }] } : {}),
  symbolLayers: [{ type: "CIMVectorMarker", enable: true, anchorPointUnits: "Relative", size: 6, scaleSymbolsProportionally: true, respectFrame: true,
    frame: { xmin: 0, ymin: 0, xmax: 20, ymax: 6 },
    markerGraphics: [mg({ paths: [wavePath] }, { type: "CIMLineSymbol", symbolLayers: [stroke(1, [30, 75, 184, 150])] })] }] });

/** half = 0|1 → every other wave (two layers cross-fade); half = null → all waves (native animation) */
export function waveLayer(world, half, native) {
  return clientLayer({ title: "Waves", geometryType: "point", fields: fields(),
    source: world.waves.filter((_, i) => half == null || i % 2 === half).map(([lon, lat], i) => new Graphic({ geometry: geo(lon, lat), attributes: { oid: i + 1 } })),
    renderer: { type: "simple", symbol: waveSym(native) } });
}

/* ------------------------------------------------------------------ rasters (resampled into the plate's SR) */
const plateExtent = () => new Extent({ xmin: -PLATE_R, ymin: -PLATE_R, xmax: PLATE_R, ymax: PLATE_R, spatialReference: SR });

/** Hillshade relief: a multi-directional hillshade (shadows only) computed by scripts/terrain.py and pre-projected
    into this plate as cobalt ink. A MediaLayer lets the GPU filter it smoothly at every zoom. */
export async function reliefLayer(url, metaUrl, opacity = 0.6) {
  const meta = await (await fetch(metaUrl)).json();
  if (Math.abs(meta.radius - PLATE_R) > 1000) console.warn("relief image was built for another plate radius", meta.radius, PLATE_R);
  return new MediaLayer({
    title: "Relief", copyright: "ETOPO1, NOAA NCEI", opacity,
    maxScale: 9_000_000,   // 10′ data: too soft closer in (a finer regional relief would go here)
    source: [new ImageElement({ image: url, georeference: new ExtentAndRotationGeoreference({ extent: plateExtent() }) })],
  });
}

// Sea currents are ~20× slower than the winds the FlowRenderer is tuned for: speed them up for the eye
const SPEEDUP = 15;
export function currentsLayer(cur, up = 3) {
  const dec = b64 => new Int16Array(Uint8Array.from(atob(b64), ch => ch.charCodeAt(0)).buffer);
  const U = dec(cur.u), V = dec(cur.v), { w, h } = cur;
  // In-memory rasters are sampled "closest", so the FlowRenderer would trace 0.8° stair-steps. Upsample ×3 with
  // bilinear interpolation here (wrapping across the date line) so the streamlines come out as smooth curves.
  const W = w * up, H = h * up, n = W * H;
  const pu = new Float32Array(n), pv = new Float32Array(n), mask = new Uint8Array(n);
  for (let r = 0; r < H; r++) {
    const fy = Math.min(h - 1, Math.max(0, (H - 1 - r + 0.5) / up - 0.5)), y0 = Math.floor(fy), y1 = Math.min(h - 1, y0 + 1), ty = fy - y0;
    for (let c = 0; c < W; c++) {
      const fx = (c + 0.5) / up - 0.5, x0 = ((Math.floor(fx) % w) + w) % w, x1 = (x0 + 1) % w, tx = fx - Math.floor(fx);
      const i00 = y0 * w + x0, i01 = y0 * w + x1, i10 = y1 * w + x0, i11 = y1 * w + x1;
      if (U[i00] === cur.nodata || U[i01] === cur.nodata || U[i10] === cur.nodata || U[i11] === cur.nodata) continue;
      const bl = A => ((A[i00] * (1 - tx) + A[i01] * tx) * (1 - ty) + (A[i10] * (1 - tx) + A[i11] * tx) * ty) / 100 * SPEEDUP;
      const o = r * W + c;   // raster rows run north → south; the source runs south → north
      pu[o] = bl(U); pv[o] = bl(V); mask[o] = 1;
    }
  }
  const pixelBlock = new PixelBlock({ width: W, height: H, pixelType: "f32", pixels: [pu, pv], mask });
  pixelBlock.updateStatistics?.();
  const extent = new Extent({ xmin: cur.lon0 - cur.dlon / 2, xmax: cur.lon0 + (w - 0.5) * cur.dlon,
    ymin: cur.lat0 - cur.dlat / 2, ymax: cur.lat0 + (h - 0.5) * cur.dlat, spatialReference: { wkid: 4326 } });
  return new ImageryTileLayer({
    title: `Ocean currents (${cur.date})`, copyright: "NOAA AOML geostrophic currents",
    source: { extent, pixelBlock, dataType: "vector-uv" },
    opacity: 0.45,
    // many thin, long, slow threads (nullschool-like) rather than short dashes
    renderer: { type: "flow", density: 0.9, flowSpeed: 3.5, trailLength: 110, trailWidth: "1px", maxPathLength: 320, trailCap: "round",
      flowRepresentation: "flow-to", color: [30, 75, 184, 1],
      visualVariables: [{ type: "opacity", field: "Magnitude", stops: [{ value: 0.02 * SPEEDUP, opacity: 0.12 }, { value: 0.35 * SPEEDUP, opacity: 0.9 }] }] },
  });
}

/* ------------------------------------------------------------------ guest card (popup content) */
// a little azulejo tile in the side's colour, for the card's header strip
const tileSvg = col => `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><rect width="40" height="40" fill="#fbf7f0"/><g fill="${col}"><ellipse cx="20" cy="11" rx="3.2" ry="6"/><ellipse cx="20" cy="29" rx="3.2" ry="6"/><ellipse cx="11" cy="20" rx="6" ry="3.2"/><ellipse cx="29" cy="20" rx="6" ry="3.2"/><circle r="6"/><circle cx="40" r="6"/><circle cy="40" r="6"/><circle cx="40" cy="40" r="6"/></g><circle cx="20" cy="20" r="2.6" fill="#fbf7f0"/></svg>`)}`;
const MODE = { Plane: "by plane", Car: "by car", Train: "by train" };
const DAYS = ["Thu", "Fri", "Sat", "Sun"];

/** The popup renders inside the arcgis-popup shadow DOM, so the card carries its own inline styles. */
export function guestCard(f) {
  const s = SIDES[f.o.side], el = document.createElement("div");
  const days = [...new Set(f.o.parties.map(p => p.arrival_day))].sort((a, b) => DAYS.indexOf(a) - DAYS.indexOf(b));
  const names = f.o.parties.map(p => esc(p.party_lead));
  const chip = (txt, strong = false) => `<span style="display:inline-block;padding:3px 9px;border-radius:999px;font:500 11px/1.4 Inter,sans-serif;letter-spacing:.02em;${strong ? `background:${s.color};color:#fbf7f0` : `background:#f1e9dc;color:#4a3b2f`}">${txt}</span>`;
  el.innerHTML = `
  <div style="font-family:Inter,sans-serif;color:#4a3b2f;margin:-2px 0 2px">
    <div style="height:12px;border-radius:3px;background:url('${tileSvg(s.color)}') 0 0/12px 12px;opacity:.85"></div>
    <div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:10px;font:600 9px/1 Inter,sans-serif;letter-spacing:.24em;text-transform:uppercase">
      <span style="color:${s.color}">${esc(s.label)}</span><span style="color:#7f8f5f">${esc(f.o.country)}</span></div>
    <div style="display:flex;align-items:baseline;gap:8px;margin:8px 0 2px">
      <span style="font:400 44px/0.9 'Instrument Serif',serif;color:#c2541f">${fmt(f.km)}</span>
      <span style="font:400 15px/1.1 'Instrument Serif',serif;font-style:italic;color:#6b5a4b">km to the Algarve</span></div>
    <div style="display:flex;flex-wrap:wrap;gap:5px;margin:10px 0 8px">
      ${chip(`${f.o.guests} guest${f.o.guests > 1 ? "s" : ""}`, true)}
      ${Object.entries(f.o.modes).map(([m, n]) => chip(`${n} ${MODE[m] || esc(m)}`)).join("")}
      ${days.length ? chip(`arriving ${days.map(esc).join(" · ")}`) : ""}</div>
    <div style="font:400 12px/1.55 Inter,sans-serif;color:#6b5a4b">${names.slice(0, 4).join(", ")}${names.length > 4 ? ` <i>+ ${names.length - 4} more</i>` : ""}</div>
    ${f.o.note ? `<div style="margin-top:10px;padding:2px 0 2px 12px;border-left:2px solid ${s.color};font:italic 400 19px/1.25 'Instrument Serif',serif;color:#1e4bb8">“${esc(f.o.note)}”</div>` : ""}
  </div>`;
  return el;
}

/* ------------------------------------------------------------------ guests */
/* One feature per city & side. Renderer, size variable, labels, popup and legend all come from the layer. */
export function guestLayer(flows) {
  return clientLayer({
    title: "Our guests", geometryType: "point", legendEnabled: true, popupEnabled: true, outFields: ["*"],
    fields: fields(["fid", "integer"], ["city", "string"], ["country", "string"], ["side", "string"], ["guests", "integer"], ["km", "double"]),
    source: flows.map(f => new Graphic({ geometry: f.xy,
      attributes: { oid: f.i + 1, fid: f.i, city: f.o.city, country: f.o.country, side: f.o.side, guests: f.o.guests, km: Math.round(f.km) } })),
    renderer: {
      type: "unique-value", field: "side",
      uniqueValueInfos: Object.entries(SIDES).map(([k, s]) => ({ value: k, label: s.label,
        symbol: { type: "simple-marker", color: "#fbf7f0", outline: { color: s.color, width: 1.6 } } })),
      visualVariables: [{ type: "size", field: "guests", legendOptions: { title: "Guests" },
        stops: [{ value: 2, size: 7, label: "2" }, { value: 10, size: 13, label: "10" }, { value: 25, size: 20, label: "25+" }] }],
    },
    labelingInfo: [{
      labelExpressionInfo: { expression: "Upper($feature.city)" },
      labelPlacement: "above-center",
      symbol: { type: "text", color: "#4a3b2f", haloColor: [251, 247, 240, 0.9], haloSize: 1.2, font: { family: "Avenir Next LT Pro", size: 8, weight: "bold" } },
    }],
    popupTemplate: {
      title: "{city}",
      outFields: ["*"],
      overwriteActions: true, actions: [],
      content: ({ graphic }) => guestCard(flows[graphic.attributes.fid]),
    },
  });
}

/* ------------------------------------------------------------------ small-scale outlines (scripts/world.py "lo") */
/** Dissolved land (fjords closed, specks dropped) with Portugal cut from it; borders come as separate lines. */
export function landLoLayer(lo, kind) {
  const s = LAND_STYLE[kind];
  const src = [...lo.land.map(r => ["land", r]), ...lo.portugal.map(r => ["Portugal", r])].map(([name, rings], i) =>
    new Graphic({ geometry: new Polygon({ rings: rings.map(projLine), spatialReference: SR }), attributes: { oid: i + 1, name } }));
  const sym = color => ({ type: "simple-fill", color, outline: { color: [0, 0, 0, 0], width: 0 } });
  return clientLayer({ title: "Countries (small scale)", geometryType: "polygon", fields: fields(["name", "string"]), source: src,
    ...(s.shadow ? { effect: s.shadow } : {}),
    renderer: { type: "unique-value", field: "name", defaultSymbol: sym(s.fill), uniqueValueInfos: [{ value: "Portugal", symbol: sym(s.portugal) }] } });
}
export function bordersLoLayer(lo, kind) {
  const s = LAND_STYLE[kind];
  return clientLayer({ title: "Borders (small scale)", geometryType: "polyline", fields: fields(),
    source: lo.borders.map((l, i) => new Graphic({ geometry: new Polyline({ paths: [projLine(l)], spatialReference: SR }), attributes: { oid: i + 1 } })),
    renderer: { type: "simple", symbol: { type: "simple-line", color: s.border, width: s.borderW } } });
}
