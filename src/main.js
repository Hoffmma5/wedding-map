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

import Map from "@arcgis/core/Map.js";
import GraphicsLayer from "@arcgis/core/layers/GraphicsLayer.js";
import Graphic from "@arcgis/core/Graphic.js";
import Point from "@arcgis/core/geometry/Point.js";
import Polyline from "@arcgis/core/geometry/Polyline.js";
import Polygon from "@arcgis/core/geometry/Polygon.js";

import { VENUE, SIDES } from "./config.js";
import { SR, geo, kmTo, PLATE_R } from "./projection.js";
import { loadRsvps, loadWorld, toOrigins } from "./data.js";
import { ring, plateLayer, graticuleLayer, rippleLayer, landLayer, waveLayer, guestLayer } from "./layers.js";

const $ = id => document.getElementById(id);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fmt = n => Math.round(n).toLocaleString("en-GB").replace(/,/g, " ");

function fail(html, err) {
  $("msg").style.display = "block";
  $("msg").innerHTML = html;
  throw err;
}

/* =========================================================================
   DATA (loaded at runtime from public/data)
   ========================================================================= */
let RSVPS, WORLD;
try {
  [RSVPS, WORLD] = await Promise.all([loadRsvps(), loadWorld()]);
} catch (e) {
  fail("<b>The guest list couldn't load.</b><br>Run <code>npm run dev</code> and open the local URL.", e);
}
const ORIGINS = toOrigins(RSVPS);

$("sideLegend").innerHTML = Object.values(SIDES).map(s => `<span><i style="background:${s.color}"></i>${s.label}</span>`).join("");

/* =========================================================================
   LAYERS
   ========================================================================= */
const NATIVE = location.hash === "#cim";   // native CIM symbol animations instead of the JS loop

const flows = ORIGINS.map((o, i) => ({ o, i, km: kmTo(o.lon, o.lat), xy: geo(o.lon, o.lat) })).sort((a, b) => b.km - a.km);
flows.forEach((f, i) => { f.i = i; });

const plateL = plateLayer();
const gratL = graticuleLayer(WORLD);
const waveA = waveLayer(WORLD, NATIVE ? null : 0, NATIVE), waveB = NATIVE ? null : waveLayer(WORLD, 1, false);
const rippleL = rippleLayer(WORLD);
const landL = landLayer(WORLD);
const originL = guestLayer(flows);

// Animated layers (geometry changes every frame, so GraphicsLayers in the view's spatial reference)
const flowL = new GraphicsLayer({ title: "Flows" }), dotL = new GraphicsLayer({ title: "Travellers" }), venueL = new GraphicsLayer({ title: "Venue" });

const map = new Map({ layers: [plateL, gratL, waveA, ...(waveB ? [waveB] : []), rippleL, landL, flowL, dotL, originL, venueL] });

/* =========================================================================
   THE MAP COMPONENT
   ========================================================================= */
const mapEl = $("map");
mapEl.spatialReference = SR;
mapEl.spatialReferenceLocked = true;
mapEl.background = { color: "#efe7da" };
mapEl.constraints = { rotationEnabled: false, minScale: 160_000_000, maxScale: 250_000 };
mapEl.extent = { xmin: -PLATE_R, ymin: -PLATE_R, xmax: PLATE_R, ymax: PLATE_R, spatialReference: SR };
mapEl.highlights = [{ name: "default", color: "#c2541f", haloOpacity: 0.9, fillOpacity: 0.15 }];
mapEl.map = map;
await mapEl.viewOnReady();
const view = mapEl.view;
try {
  Object.assign(mapEl.popupElement, { dockEnabled: true, dockOptions: { buttonEnabled: false, breakpoint: false, position: "bottom-right" } });
} catch (e) { console.warn("popup dock", e); }
const HOME = { center: geo(6, 45.5), scale: 20_000_000 };   // Europe, from the Algarve to Berlin and Cyprus
const WORLDVIEW = { target: new Polygon({ rings: [ring(PLATE_R, 8)], spatialReference: SR }) };

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
  const f = p * (pts.length - 1), i = Math.min(pts.length - 2, Math.floor(f)), r = f - i, a = pts[i], b = pts[i + 1];
  return [a[0] + (b[0] - a[0]) * r, a[1] + (b[1] - a[1]) * r];
}
const line = pts => new Polyline({ paths: [pts], spatialReference: SR });
const pt = ([x, y]) => new Point({ x, y, spatialReference: SR });

const dotPath = Array.from({ length: 17 }, (_, i) => [Math.cos(i / 16 * 2 * Math.PI) * 5, Math.sin(i / 16 * 2 * Math.PI) * 5]);
flows.forEach((f, i) => {
  const col = SIDES[f.o.side].color;
  f.pts = curve(f.xy, V);
  f.w = 1.2 + Math.sqrt(f.o.guests) * 0.8;
  f.delay = 300 + i * 420;
  f.dur = Math.min(4200, 1300 + Math.sqrt(f.km) * 30);
  f.period = Math.min(14000, 2600 + f.km * 1.0);
  f.phase = (i * 0.37) % 1;
  f.drawSym = { type: "simple-line", color: rgba(col, 0.87), width: f.w * 0.75, cap: "round", join: "round" };
  f.halo = new Graphic({ symbol: { type: "simple-line", color: rgba(col, 0.13), width: (f.w + 5) * 0.75, cap: "round", join: "round" } });
  f.line = new Graphic({ symbol: f.drawSym });
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
   TIMELINE
   ========================================================================= */
let t0 = performance.now(), arrived = new Set(), cameraTimer = null;
const target = { g: 0, c: 0, km: 0 }, shown = { g: 0, c: 0, km: 0 };
const ease = p => 1 - Math.pow(1 - Math.max(0, Math.min(1, p)), 3);

function restart() {
  mapEl.closePopup();
  t0 = performance.now(); arrived = new Set();
  Object.assign(target, { g: 0, c: 0, km: 0 }); Object.assign(shown, target);
  flowL.removeAll(); dotL.removeAll();
  flows.forEach(f => { f.state = "wait"; f.dots = null; f.line.symbol = f.drawSym; });
  clearTimeout(cameraTimer);
  view.goTo(WORLDVIEW, { duration: 1200 }).catch(() => {});
  const last = Math.max(...flows.map(f => f.delay + f.dur));
  cameraTimer = setTimeout(() => view.goTo(HOME, { duration: 4500, easing: "in-out-cubic" }).catch(() => {}), last - 600);
}

function frame(now) {
  for (const f of flows) {
    const p = (now - t0 - f.delay) / f.dur;
    if (p <= 0) continue;
    if (f.state === "wait") { f.state = "draw"; flowL.addMany([f.halo, f.line]); }
    if (f.state === "draw") {
      const g = line(partial(f.pts, ease(p)));
      f.halo.geometry = g; f.line.geometry = g;
      if (p >= 1) {
        f.state = "done"; arrived.add(f);
        target.g += f.o.guests; target.km += f.km * f.o.guests; target.c = new Set([...arrived].map(x => x.o.country)).size;
        if (NATIVE) f.line.symbol = f.nativeSym;
        else { f.dots = [0, 0.5].map(off => new Graphic({ attributes: { off }, symbol: { type: "simple-marker", size: (1.2 + f.w * 0.45) * 1.5, color: "#fbf7f0", outline: null } })); dotL.addMany(f.dots); }
      }
    }
    if (f.dots) for (const d of f.dots) d.geometry = pt(along(f.pts, ((now / f.period) + f.phase + d.attributes.off) % 1));
  }
  if (!NATIVE) { const b = 0.5 + 0.5 * Math.sin(now / 1400); waveA.opacity = 0.35 + 0.65 * b; waveB.opacity = 0.35 + 0.65 * (1 - b); }
  const beat = (now % 1800) / 1800;
  pulse.symbol = { type: "simple-marker", size: 18 + beat * 30, color: [0, 0, 0, 0], outline: { color: [194, 84, 31, 0.55 * (1 - beat)], width: 1.5 } };
  for (const k of ["g", "c", "km"]) shown[k] += (target[k] - shown[k]) * 0.09;
  $("sGuests").textContent = fmt(shown.g); $("sCountries").textContent = fmt(shown.c); $("sKm").textContent = fmt(shown.km);
  requestAnimationFrame(frame);
}

/* =========================================================================
   INTERACTION: replay + guest tour (camera flights + the Esri popup)
   ========================================================================= */
let tourOn = false;
$("replay").addEventListener("click", restart);
$("tour").addEventListener("click", async () => {
  if (tourOn) { tourOn = false; return; }
  tourOn = true; $("tour").textContent = "Stop tour";
  clearTimeout(cameraTimer);
  const { features } = await originL.queryFeatures({ where: "1=1", outFields: ["*"], returnGeometry: true });
  features.sort((a, b) => b.attributes.km - a.attributes.km);
  for (const g of features) {
    if (!tourOn) break;
    await view.goTo({ target: g.geometry, scale: g.attributes.km > 3500 ? 18_000_000 : 5_000_000 }, { duration: 2200 }).catch(() => {});
    await mapEl.openPopup({ features: [g], location: g.geometry });
    await sleep(3200);
  }
  mapEl.closePopup();
  await view.goTo(HOME, { duration: 2500 }).catch(() => {});
  tourOn = false; $("tour").textContent = "Guest tour";
});

restart();
requestAnimationFrame(frame);
if (import.meta.env.DEV) window.__wedding = { mapEl, view, flows, originL, map, Point,
  projectOperator: () => import("@arcgis/core/geometry/operators/projectOperator.js") };
