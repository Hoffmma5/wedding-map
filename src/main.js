/* Everyone's coming to the Algarve: guest flow map.
   ArcGIS Maps SDK for JavaScript (map components + core) + Calcite, bundled with Vite. */
import "@esri/calcite-components/main.css";
import "@arcgis/core/assets/esri/themes/light/main.css";
import "./style.css";

import "@arcgis/map-components/components/arcgis-map";
import "@arcgis/map-components/components/arcgis-zoom";
import "@arcgis/map-components/components/arcgis-home";
import "@arcgis/map-components/components/arcgis-expand";
import "@arcgis/map-components/components/arcgis-legend";
import "@esri/calcite-components/components/calcite-button";
import "@esri/calcite-components/components/calcite-segmented-control";
import "@esri/calcite-components/components/calcite-segmented-control-item";
import "@esri/calcite-components/components/calcite-chip";
import "@esri/calcite-components/components/calcite-chip-group";

import Map from "@arcgis/core/Map.js";
import * as reactiveUtils from "@arcgis/core/core/reactiveUtils.js";
import GraphicsLayer from "@arcgis/core/layers/GraphicsLayer.js";
import Graphic from "@arcgis/core/Graphic.js";
import Point from "@arcgis/core/geometry/Point.js";
import Polyline from "@arcgis/core/geometry/Polyline.js";

import { VENUE, SIDES, DATA } from "./config.js";
import { VARIANT, buildPanel } from "./variants.js";
import { canvasRim } from "./rim.js";
import { SR, geo, kmTo, PLATE_R, PROJECTION } from "./projection.js";
import { loadRsvps, loadWorld, loadJson, toOrigins } from "./data.js";
import { ring, seaLayer, maskLayer, rimLayer, graticuleLayer, rippleLayer, landLayer, contourLayer, waveLayer,
  reliefLayer, currentsLayer, guestLayer, inkLayer, landLoLayer, bordersLoLayer, LAND_STYLE } from "./layers.js";

const $ = id => document.getElementById(id);
const fmt = n => Math.round(n).toLocaleString("en-GB").replace(/,/g, " ");

function fail(html, err) {
  $("msg").style.display = "block";
  $("msg").innerHTML = html;
  throw err;
}

buildPanel($("design"));
$("sideLegend").innerHTML = Object.values(SIDES).map(s => `<span><i style="background:${s.color}"></i>${s.label}</span>`).join("");

/* =========================================================================
   DATA (loaded at runtime from public/data, only what the chosen variant needs)
   ========================================================================= */
const SEA = new Set(VARIANT.sea), LAND = VARIANT.land, ARRIVE = VARIANT.flows === "arrive", NATIVE = VARIANT.cim;
// client-side rasters are projected through the projection engine, so load it up front (≈1 s, cached)
const needContours = SEA.has("contours"), needDem = LAND !== "sage";
let RSVPS, WORLD, CONTOURS, CURRENTS;
try {
  [RSVPS, WORLD, CONTOURS, CURRENTS] = await Promise.all([
    loadRsvps(), loadWorld(),
    needContours ? loadJson(DATA.contours) : null,
    SEA.has("currents") ? loadJson(DATA.currents) : null,
  ]);
} catch (e) {
  fail("<b>The guest list couldn't load.</b><br>Run <code>npm run dev</code> and open the local URL.", e);
}
const ORIGINS = toOrigins(RSVPS);

/* =========================================================================
   LAYERS (bottom → top): sea, sea decoration, coastal lines, land, relief, mask, rim, flows, guests, venue
   ========================================================================= */
// A guest from beyond the plate's edge (Darwin, 136°) starts on the rim, in the true direction of home: on an
// azimuthal map every direction from the venue is true, so only the distance is cut short.
const onPlate = (lon, lat) => {
  const p = geo(lon, lat), r = Math.hypot(p.x, p.y), max = PLATE_R * 0.975;
  return r <= max ? { xy: p, beyond: false } : { xy: new Point({ x: p.x * max / r, y: p.y * max / r, spatialReference: SR }), beyond: true };
};
const flows = ORIGINS.map((o, i) => ({ o, i, km: kmTo(o.lon, o.lat), ...onPlate(o.lon, o.lat) })).sort((a, b) => b.km - a.km);
flows.forEach((f, i) => { f.i = i; });

const waveA = SEA.has("waves") ? waveLayer(WORLD, NATIVE ? null : 0, NATIVE) : null;
const waveB = SEA.has("waves") && !NATIVE ? waveLayer(WORLD, 1, false) : null;
const TIMING = import.meta.env.DEV || location.search.includes("timing");
const mark = s => TIMING && console.info(`[timing] ${s}: ${Math.round(performance.now())} ms since page start`);
mark("data loaded");
// Two generalizations: detailed from the Europe zoom (1:20M) inwards, a calmer one for the whole-world view. The
// land of both overlaps between 1:30M and 1:45M (the small-scale land on top), so while zooming through the switch
// one land is always already drawn; water lines and ink switch at 1:38M, inside that overlap.
const SWITCH = { lines: 38_000_000, landHi: 45_000_000, landLo: 30_000_000 };
const hiSet = (l, s = SWITCH.lines) => { if (l) l.minScale = s; return l; };
const loSet = (l, s = SWITCH.lines) => { if (l) l.maxScale = s; return l; };
const INK = LAND_STYLE[LAND].coast;
const decor = [
  graticuleLayer(WORLD),
  waveA, waveB,
  SEA.has("contours") ? contourLayer(CONTOURS, "sea") : null,
  hiSet(rippleLayer({ coast: WORLD.ripple })), loSet(rippleLayer(WORLD.lo)),   // water lines: a lighter copy of the inked coast
  INK ? hiSet(inkLayer(WORLD, INK)) : null, INK ? loSet(inkLayer(WORLD.lo, INK)) : null,
  hiSet(landLayer(WORLD, LAND), SWITCH.landHi), loSet(landLoLayer(WORLD.lo, LAND), SWITCH.landLo), loSet(bordersLoLayer(WORLD.lo, LAND), SWITCH.landLo),
  needDem ? await reliefLayer(DATA.relief(PROJECTION), DATA.reliefMeta(PROJECTION), LAND_STYLE[LAND].relief) : null,
].filter(Boolean);
mark("layers built");
const originL = guestLayer(flows);

// Animated layers (geometry changes every frame, so GraphicsLayers in the view's spatial reference)
const flowL = new GraphicsLayer({ title: "Flows" }), dotL = new GraphicsLayer({ title: "Travellers" }), venueL = new GraphicsLayer({ title: "Venue" });

const map = new Map({ layers: [seaLayer(), ...decor, maskLayer(), ...(VARIANT.rim === "tiles" ? [] : [rimLayer(VARIANT.rim)]), flowL, dotL, originL, venueL] });

/* =========================================================================
   THE MAP COMPONENT
   ========================================================================= */
const mapEl = $("map");
mapEl.spatialReference = SR;
mapEl.spatialReferenceLocked = true;
mapEl.background = { color: "#efe7da" };
// Explicit zoom levels: otherwise the first tiled layer (an in-memory ImageryTileLayer) dictates them, which locks the zoom.
const lods = Array.from({ length: 24 }, (_, level) => { const scale = 600_000_000 / 2 ** (level / 2); return { level, scale, resolution: scale / (39.37 * 96) }; });
mapEl.constraints = { rotationEnabled: false, snapToZoom: false, lods, minScale: 600_000_000, maxScale: 250_000 };
mapEl.extent = { xmin: -PLATE_R, ymin: -PLATE_R, xmax: PLATE_R, ymax: PLATE_R, spatialReference: SR };
// one highlight group per side, so a hovered city glows in its own side's colour
mapEl.highlights = [
  { name: "default", color: "#c2541f", haloOpacity: 0.9, fillOpacity: 0.15 },
  ...Object.entries(SIDES).map(([k, s]) => ({ name: `side-${k}`, color: s.color, haloOpacity: 0.9, fillOpacity: 0.15 })),
];
mapEl.map = map;
await mapEl.viewOnReady();
mark("view ready");
const view = mapEl.view;
if (VARIANT.rim === "tiles") canvasRim(view, geo(VENUE.lon, VENUE.lat), PLATE_R);   // azulejo rim, exact at every zoom
if (TIMING) for (const l of map.layers) view.whenLayerView(l).then(lv => reactiveUtils.whenOnce(() => !lv.updating)).then(() => mark(`drawn: ${l.title}`));
try {
  // a clean card: no "Zoom to" action bar, no collapse or paging controls
  Object.assign(mapEl.popupElement, { dockEnabled: true, dockOptions: { buttonEnabled: false, breakpoint: false, position: "bottom-right" },
    hideActionBar: true, hideCollapseButton: true, hideFeatureNavigation: true,
    highlightEnabled: false });   // the card's city is highlighted by us, in its side's colour (see show())
} catch (e) { console.warn("popup dock", e); }
const HOME = { center: geo(6, 45.5), scale: 20_000_000 };   // Europe, from the Algarve to Berlin and Cyprus
// the whole plate plus its rim (≈50 px), whatever the screen shape
const worldView = () => ({ center: geo(VENUE.lon, VENUE.lat), scale: (2 * PLATE_R) / Math.max(120, Math.min(view.width, view.height) - 130) * 96 * 39.37 });

/* =========================================================================
   FLOWS: curved, always bending the same way, drawn in the view's coordinates
   ========================================================================= */
const V = geo(VENUE.lon, VENUE.lat);
const rgba = (hex, a) => [parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16), a];
function curve(a, b, n = 72) {
  const dx = b.x - a.x, dy = b.y - a.y, c = [(a.x + b.x) / 2 - dy * 0.22, (a.y + b.y) / 2 + dx * 0.22];
  return Array.from({ length: n + 1 }, (_, i) => { const t = i / n, u = 1 - t; return [u * u * a.x + 2 * u * t * c[0] + t * t * b.x, u * u * a.y + 2 * u * t * c[1] + t * t * b.y]; });
}
function partial(pts, p) {
  const f = Math.max(0, Math.min(1, p)) * (pts.length - 1), i = Math.floor(f), r = f - i, out = pts.slice(0, i + 1);
  if (i < pts.length - 1) { const a = pts[i], b = pts[i + 1]; out.push([a[0] + (b[0] - a[0]) * r, a[1] + (b[1] - a[1]) * r]); }
  return out;
}
function along(pts, p) {
  const f = Math.max(0, Math.min(1, p)) * (pts.length - 1), i = Math.min(pts.length - 2, Math.floor(f)), r = f - i, a = pts[i], b = pts[i + 1];
  return [a[0] + (b[0] - a[0]) * r, a[1] + (b[1] - a[1]) * r];
}
const line = pts => new Polyline({ paths: [pts], spatialReference: SR });
const pt = ([x, y]) => new Point({ x, y, spatialReference: SR });

const dotPath = Array.from({ length: 17 }, (_, i) => [Math.cos(i / 16 * 2 * Math.PI) * 5, Math.sin(i / 16 * 2 * Math.PI) * 5]);
flows.forEach((f, i) => {
  const col = SIDES[f.o.side].color;
  f.col = col;
  f.pts = curve(f.xy, V);
  f.w = 1.2 + Math.sqrt(f.o.guests) * 0.8;
  f.delay = 300 + i * 420;
  f.dur = Math.min(4200, 1300 + Math.sqrt(f.km) * 30);
  f.period = Math.min(14000, 2600 + f.km * 1.0);
  f.phase = (i * 0.37) % 1;
  f.drawSym = { type: "simple-line", color: rgba(col, 0.87), width: f.w * 0.75, cap: "round", join: "round" };
  f.hotSym = { type: "simple-line", color: rgba(col, 1), width: f.w * 0.75 + 1.4, cap: "round", join: "round" };
  f.haloSym = { type: "simple-line", color: rgba(col, 0.13), width: (f.w + 5) * 0.75, cap: "round", join: "round" };
  f.haloHot = { type: "simple-line", color: rgba(col, 0.28), width: (f.w + 9) * 0.75, cap: "round", join: "round" };
  f.halo = new Graphic({ symbol: f.haloSym, attributes: { fid: i } });     // the wide halo is the easy hover target
  f.line = new Graphic({ symbol: f.drawSym, attributes: { fid: i } });
  // "arrive" mode: one traveller rides the tip of the line, and lands with a ripple at the venue
  f.traveller = new Graphic({ symbol: { type: "simple-marker", size: 4 + f.w * 0.9, color: "#fbf7f0", outline: { color: col, width: 1.4 } } });
  // native variant: cream dots travel along the finished flow (CIMSymbolAnimationMoveAlongLine, beta)
  f.nativeSym = { type: "cim", data: { type: "CIMSymbolReference", symbol: { type: "CIMLineSymbol", symbolLayers: [
    { type: "CIMVectorMarker", enable: true, anchorPointUnits: "Relative", size: 2 + f.w * 0.4, frame: { xmin: -5, ymin: -5, xmax: 5, ymax: 5 },
      markerGraphics: [{ type: "CIMMarkerGraphic", geometry: { rings: [dotPath] }, symbol: { type: "CIMPolygonSymbol", symbolLayers: [{ type: "CIMSolidFill", enable: true, color: [251, 247, 240, 255] }] } }],
      markerPlacement: { type: "CIMMarkerPlacementAlongLineSameSize", angleToLine: true, placementTemplate: [70] },
      animations: [{ type: "CIMSymbolAnimationMoveAlongLine", movementType: "Speed", speed: 18, continuous: true, animatedSymbolProperties: { playAnimation: true, repeatType: "Loop", easing: "Linear" } }] },
    { type: "CIMSolidStroke", enable: true, width: f.w * 0.75, color: [...rgba(col, 0).slice(0, 3), 222], capStyle: "Round", joinStyle: "Round" },
  ] } } };
});

// Venue: an orange (picture marker) with a pulsing ring
const ORANGE_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><radialGradient id="o" cx=".38" cy=".38" r=".7"><stop offset="0" stop-color="#ffb35a"/><stop offset=".7" stop-color="#e8892b"/><stop offset="1" stop-color="#c5631a"/></radialGradient></defs><path d="M32 18 C38 6 52 6 58 10 C50 18 40 20 32 18Z" fill="#4f7a3a"/><path d="M31 18 C24 8 12 8 7 12 C14 19 24 20 31 18Z" fill="#6b9450"/><circle cx="32" cy="38" r="22" fill="url(#o)" stroke="#b9561a" stroke-width="1"/><g fill="#fff"><circle cx="46" cy="16" r="2.6"/><circle cx="49.5" cy="14" r="2.2"/><circle cx="49.5" cy="18.4" r="2.2"/></g><circle cx="48" cy="16" r="1.2" fill="#f2c94c"/></svg>`;
const pulse = new Graphic({ geometry: V, symbol: { type: "simple-marker", size: 20, color: [0, 0, 0, 0], outline: { color: [194, 84, 31, 0.5], width: 1.5 } } });
venueL.addMany([pulse, new Graphic({ geometry: V, symbol: { type: "picture-marker", url: "data:image/svg+xml;charset=utf-8," + encodeURIComponent(ORANGE_SVG), width: 28, height: 28, yoffset: 3 },
  popupTemplate: { title: "The venue", content: `${VENUE.place} · where everyone is heading` } })]);

/* =========================================================================
   TIMELINE. The loop only runs while something moves (intro, travellers, ripples, counters) and then sleeps,
   so a settled map costs nothing per frame and the SDK has the main thread to itself.
   ========================================================================= */
let t0 = performance.now(), arrived = new Set(), cameraTimer = null, running = false;
const target = { g: 0, c: 0, km: 0 }, shown = { g: 0, c: 0, km: 0 }, statText = { g: "", c: "", km: "" };
const ease = p => 1 - Math.pow(1 - Math.max(0, Math.min(1, p)), 3);
const easeInOut = p => (p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2);
const ripples = [];      // landing ripples at the venue: { g, t, col }
const trips = new Set(); // "arrive" mode: travellers re-running a route on hover / click
const ALWAYS = !ARRIVE || !!(waveA && waveB);   // looping dots / cross-fading waves need every frame
const STAT = { g: "sGuests", c: "sCountries", km: "sKm" };

// "arrive" mode: a quiet, static ring around the orange; the life comes from the landing ripples
if (ARRIVE) pulse.symbol = { type: "simple-marker", size: 32, color: [0, 0, 0, 0], outline: { color: [194, 84, 31, 0.25], width: 1.2 } };

function kick() { if (!running) { running = true; requestAnimationFrame(frame); } }

function ripple(col, now) {
  const g = new Graphic({ geometry: V });
  venueL.add(g, 0);
  ripples.push({ g, t: now, col });
}

/** send one traveller along a finished route (hover, click) */
function trip(f, now = performance.now()) {
  if (!ARRIVE || f.state !== "done" || (f.tripT && now - f.tripT < f.tripDur + 600)) return;
  f.tripT = now; f.tripDur = Math.min(3200, 1100 + Math.sqrt(f.km) * 22);
  if (!dotL.graphics.includes(f.traveller)) dotL.add(f.traveller);
  trips.add(f);
  kick();
}

function restart() {
  mapEl.closePopup();
  t0 = performance.now(); arrived = new Set();
  Object.assign(target, { g: 0, c: 0, km: 0 }); Object.assign(shown, target);
  flowL.removeAll(); dotL.removeAll(); trips.clear();
  flows.forEach(f => { f.state = "wait"; f.dots = null; f.tripT = 0; f.line.symbol = f.drawSym; f.halo.symbol = f.haloSym; });
  hot = null;
  clearTimeout(cameraTimer);
  view.goTo(worldView(), { duration: 1200 }).catch(() => {});
  const last = Math.max(...flows.map(f => f.delay + f.dur));
  cameraTimer = setTimeout(() => view.goTo(HOME, { duration: 4500, easing: "in-out-cubic" }).catch(() => {}), last - 600);
  kick();
}

function frame(now) {
  let busy = false;
  for (const f of flows) {
    if (f.state === "done" && !f.dots) continue;
    busy = true;
    const p = (now - t0 - f.delay) / f.dur;
    if (p <= 0) continue;
    if (f.state === "wait") { f.state = "draw"; flowL.addMany([f.halo, f.line]); if (ARRIVE) dotL.add(f.traveller); }
    if (f.state === "draw") {
      const e = ease(p), pts = partial(f.pts, e), g = line(pts);
      f.halo.geometry = g; f.line.geometry = g;
      if (ARRIVE) f.traveller.geometry = pt(pts[pts.length - 1]);
      if (p >= 1) {
        f.state = "done"; arrived.add(f);
        target.g += f.o.guests; target.km += f.km * f.o.guests; target.c = new Set([...arrived].map(x => x.o.country)).size;
        if (ARRIVE) { dotL.remove(f.traveller); ripple(f.col, now); }
        else if (NATIVE) f.line.symbol = f.nativeSym;
        else { f.dots = [0, 0.5].map(off => new Graphic({ attributes: { off }, symbol: { type: "simple-marker", size: (1.2 + f.w * 0.45) * 1.5, color: "#fbf7f0", outline: null } })); dotL.addMany(f.dots); }
      }
    }
    if (f.dots) for (const d of f.dots) d.geometry = pt(along(f.pts, ((now / f.period) + f.phase + d.attributes.off) % 1));
  }
  for (const f of trips) {
    busy = true;
    const p = (now - f.tripT) / f.tripDur;
    if (p >= 1) { trips.delete(f); dotL.remove(f.traveller); ripple(f.col, now); continue; }
    f.traveller.geometry = pt(along(f.pts, easeInOut(p)));
  }
  for (let i = ripples.length - 1; i >= 0; i--) {
    busy = true;
    const r = ripples[i], p = (now - r.t) / 1600;
    if (p >= 1) { venueL.remove(r.g); ripples.splice(i, 1); continue; }
    r.g.symbol = { type: "simple-marker", size: 14 + ease(p) * 40, color: [0, 0, 0, 0], outline: { color: rgba(r.col, 0.7 * (1 - p)), width: 1.6 } };
  }
  if (waveA && waveB) { const b = 0.5 + 0.5 * Math.sin(now / 1400); waveA.opacity = 0.35 + 0.65 * b; waveB.opacity = 0.35 + 0.65 * (1 - b); }
  if (!ARRIVE) {
    const beat = (now % 1800) / 1800;
    pulse.symbol = { type: "simple-marker", size: 18 + beat * 30, color: [0, 0, 0, 0], outline: { color: [194, 84, 31, 0.55 * (1 - beat)], width: 1.5 } };
  }
  for (const k of ["g", "c", "km"]) {   // counters: touch the DOM only when the shown number changes
    const d = target[k] - shown[k];
    shown[k] = Math.abs(d) < 0.5 ? target[k] : shown[k] + d * 0.09;
    if (shown[k] !== target[k]) busy = true;
    const txt = fmt(shown[k]);
    if (txt !== statText[k]) { statText[k] = txt; $(STAT[k]).textContent = txt; }
  }
  if (busy || ALWAYS) requestAnimationFrame(frame); else running = false;
}

/* =========================================================================
   INTERACTION: hovering a city or its route highlights it, sends a traveller and shows the guest card;
   a tap does the same on touch screens. Replay restarts the intro.
   ========================================================================= */
let guestFeatures = null;   // origin features by fid, for opening the card from a route
const featureFor = async fid => {
  guestFeatures ??= originL.queryFeatures({ where: "1=1", outFields: ["*"], returnGeometry: true })
    .then(({ features }) => Object.fromEntries(features.map(g => [g.attributes.fid, g])));
  return (await guestFeatures)[fid];
};
let hot = null, hoverPopup = false, leaveTimer = null;
function setHot(f) {
  if (hot === f) return;
  if (hot) { hot.line.symbol = hot.drawSym; hot.halo.symbol = hot.haloSym; }
  hot = f;
  if (f && f.state !== "wait") { f.line.symbol = f.hotSym; f.halo.symbol = f.haloHot; }
}
async function hitFlow(e) {
  const { results } = await view.hitTest(e, { include: [originL, flowL] });
  // a city beats a route that happens to pass under the cursor
  const r = results.find(x => x.graphic?.layer === originL) ?? results.find(x => x.graphic?.attributes?.fid != null);
  return r ? flows[r.graphic.attributes.fid] : null;
}
let shownFid = null;
let originLV = null, hl = null;
view.whenLayerView(originL).then(lv => { originLV = lv; });
const clearHighlight = () => { hl?.remove(); hl = null; };
reactiveUtils.watch(() => mapEl.popupElement?.open, open => { if (!open) clearHighlight(); });
async function show(f, viaHover) {
  setHot(f); trip(f);
  const pe = mapEl.popupElement, isOpen = !!(pe && (pe.open ?? pe.visible));
  if (shownFid === f.i && isOpen) { if (!viaHover) hoverPopup = false; return; }
  const g = await featureFor(f.i);
  if (!g) return;
  shownFid = f.i; hoverPopup = viaHover;
  await mapEl.openPopup({ features: [g], location: g.geometry });
  clearHighlight();
  hl = originLV?.highlight(g, { name: `side-${f.o.side}` }) ?? null;
}
// One hit test at a time, but never drop the *last* position: where the cursor comes to rest is what counts.
let hoverBusy = false, pendingMove = null;
async function onHover(e) {
  hoverBusy = true;
  try {
    const f = await hitFlow(e);
    mapEl.style.cursor = f ? "pointer" : "";
    if (f) { clearTimeout(leaveTimer); leaveTimer = null; await show(f, true); }
    else if (hot && !leaveTimer) leaveTimer = setTimeout(() => {   // leaving: let go of the highlight, close a hover-opened card
      leaveTimer = null; setHot(null);
      if (hoverPopup) { mapEl.closePopup(); shownFid = null; }
    }, 900);
  } finally {
    hoverBusy = false;
    if (pendingMove) { const next = pendingMove; pendingMove = null; onHover(next); }
  }
}
view.on("pointer-move", (e) => {
  if (e.pointerType === "touch") return;
  if (hoverBusy) pendingMove = e; else onHover(e);
});
view.on("click", async (e) => {
  e.stopPropagation();   // we open the card ourselves (routes have no popup of their own)
  const f = await hitFlow(e);
  if (f) { clearTimeout(leaveTimer); leaveTimer = null; await show(f, false); }
  else { mapEl.closePopup(); shownFid = null; setHot(null); }
});


// let the layers finish their first draw before the intro starts, so the flows don't compete with tessellation
await Promise.race([reactiveUtils.whenOnce(() => !view.updating), new Promise(r => setTimeout(r, 2500))]);
restart();

// The currents need the projection engine (several MB of WebAssembly) to go from WGS84 into the plate. Load it only
// once the map is up, then slide the layer in under the coastlines.
if (SEA.has("currents")) import("@arcgis/core/geometry/operators/projectOperator.js").then(m => m.load()).then(() => {
  const cur = currentsLayer(CURRENTS);
  map.add(cur, map.layers.indexOf(map.layers.find(l => l.title === "Coastal water lines")));
  mark("currents added");
}).catch(e => console.warn("currents unavailable", e));
if (import.meta.env.DEV) window.__wedding = { mapEl, view, flows, originL, map, Point, VARIANT,
  projectOperator: () => import("@arcgis/core/geometry/operators/projectOperator.js") };
