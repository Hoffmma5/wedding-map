/* LAYERS: client-side FeatureLayers (renderers, labels, popups, legend) + GraphicsLayers for animation */
import FeatureLayer from "@arcgis/core/layers/FeatureLayer.js";
import GraphicsLayer from "@arcgis/core/layers/GraphicsLayer.js";
import Graphic from "@arcgis/core/Graphic.js";
import Polyline from "@arcgis/core/geometry/Polyline.js";
import Polygon from "@arcgis/core/geometry/Polygon.js";
import { SR, laea, geo, PLATE_R } from "./projection.js";
import { SIDES } from "./config.js";

export const ring = (r, n = 180) => Array.from({ length: n + 1 }, (_, i) => [Math.cos(i / n * 2 * Math.PI) * r, Math.sin(i / n * 2 * Math.PI) * r]);
const flower = Array.from({ length: 33 }, (_, i) => { const a = i / 32 * 2 * Math.PI, r = 3 + 2 * Math.abs(Math.cos(2 * a)); return [Math.cos(a) * r, Math.sin(a) * r]; });
const fmt = n => Math.round(n).toLocaleString("en-GB").replace(/,/g, " ");
// RSVP text will come from guests (Survey123), so never inject it as raw HTML
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const fields = (...f) => [{ name: "oid", type: "oid" }, ...f.map(([name, type]) => ({ name, type }))];
const clientLayer = (o) => new FeatureLayer({ objectIdField: "oid", spatialReference: SR, legendEnabled: false, popupEnabled: false, ...o });

// The world as a plate: sea disc with an azulejo rim (static CIM symbol: strokes + flower markers along the line)
export function plateLayer() {
  const layer = new GraphicsLayer({ title: "Plate" });
  layer.add(new Graphic({
    geometry: new Polygon({ rings: [ring(PLATE_R)], spatialReference: SR }),
    symbol: { type: "cim", data: { type: "CIMSymbolReference", symbol: { type: "CIMPolygonSymbol", symbolLayers: [
      { type: "CIMVectorMarker", enable: true, anchorPointUnits: "Relative", size: 9, frame: { xmin: -5, ymin: -5, xmax: 5, ymax: 5 },
        markerGraphics: [{ type: "CIMMarkerGraphic", geometry: { rings: [flower] }, symbol: { type: "CIMPolygonSymbol", symbolLayers: [{ type: "CIMSolidFill", enable: true, color: [30, 75, 184, 255] }] } }],
        markerPlacement: { type: "CIMMarkerPlacementAlongLineSameSize", placementTemplate: [16], angleToLine: true, offset: -9 } },
      { type: "CIMSolidStroke", enable: true, width: 2, color: [30, 75, 184, 255] },
      { type: "CIMSolidStroke", enable: true, width: 24, color: [251, 247, 240, 255] },
      { type: "CIMSolidFill", enable: true, color: [223, 232, 242, 255] },
    ] } } },
  }));
  return layer;
}

export function graticuleLayer(world) {
  return clientLayer({ title: "Graticule", geometryType: "polyline", fields: fields(),
    source: world.grat.map((p, i) => new Graphic({ geometry: new Polyline({ paths: [p.map(([lon, lat]) => laea(lon, lat))], spatialReference: SR }), attributes: { oid: i + 1 } })),
    renderer: { type: "simple", symbol: { type: "simple-line", color: [30, 75, 184, 0.10], width: 0.6 } } });
}

const landSource = (world) => world.countries.map((c, i) => new Graphic({
  geometry: new Polygon({ rings: c.r.map(r => { const o = []; for (let k = 0; k < r.length; k += 2) o.push(laea(r[k], r[k + 1])); return o; }), spatialReference: SR }),
  attributes: { oid: i + 1, name: c.n } }));

// Coastal water lines: a CIM polygon symbol of stacked strokes drawn *under* the land
export function rippleLayer(world) {
  return clientLayer({ title: "Coastal water lines", geometryType: "polygon", fields: fields(["name", "string"]), source: landSource(world),
    renderer: { type: "simple", symbol: { type: "cim", data: { type: "CIMSymbolReference", symbol: { type: "CIMPolygonSymbol",
      symbolLayers: [3, 7.5, 12].flatMap((d, k) => [
        { type: "CIMSolidStroke", enable: true, width: 2 * d - 0.8, color: [223, 232, 242, 255], joinStyle: "Round" },
        { type: "CIMSolidStroke", enable: true, width: 2 * d + 0.8, color: [30, 75, 184, Math.round(255 * 0.16 * (1 - k / 4))], joinStyle: "Round" },
      ]) } } } } });
}

export function landLayer(world) {
  return clientLayer({ title: "Countries", geometryType: "polygon", fields: fields(["name", "string"]), source: landSource(world),
    effect: "drop-shadow(1px, 2px, 0px rgba(96,110,70,0.35))",
    renderer: { type: "unique-value", field: "name",
      defaultSymbol: { type: "simple-fill", color: "#c9d2ad", outline: { color: "#f4eee3", width: 0.7 } },
      uniqueValueInfos: [{ value: "Portugal", symbol: { type: "simple-fill", color: "#e3a57c", outline: { color: "#f4eee3", width: 0.7 } } }] } });
}

// Ocean waves: a little hand-drawn "~" as a CIM vector marker. With #cim in the URL they animate natively (CIM symbol animations).
const wavePath = Array.from({ length: 13 }, (_, i) => [i / 12 * 20, 3 + Math.sin(i / 12 * Math.PI * 2) * 2.4]);
const waveSym = (anim) => ({ type: "cim", data: { type: "CIMSymbolReference", symbol: {
  type: "CIMPointSymbol",
  ...(anim ? { animations: [
    { type: "CIMSymbolAnimationOffset", offsetX: 4, offsetY: 1, animatedSymbolProperties: { playAnimation: true, repeatType: "Oscillate", easing: "EaseInOut", duration: 3.2, randomizeStartTime: true } },
    { type: "CIMSymbolAnimationTransparency", toTransparency: 85, animatedSymbolProperties: { playAnimation: true, repeatType: "Oscillate", easing: "EaseInOut", duration: 4.1, randomizeStartTime: true } }] } : {}),
  symbolLayers: [{ type: "CIMVectorMarker", enable: true, anchorPointUnits: "Relative", size: 6, scaleSymbolsProportionally: true, respectFrame: true,
    frame: { xmin: 0, ymin: 0, xmax: 20, ymax: 6 },
    markerGraphics: [{ type: "CIMMarkerGraphic", geometry: { paths: [wavePath] },
      symbol: { type: "CIMLineSymbol", symbolLayers: [{ type: "CIMSolidStroke", enable: true, width: 1, color: [30, 75, 184, 150], capStyle: "Round", joinStyle: "Round" }] } }] }] } } });

/** half = 0|1 → every other wave (two layers cross-fade); half = null → all waves (native animation) */
export function waveLayer(world, half, native) {
  return clientLayer({ title: "Waves", geometryType: "point", fields: fields(),
    source: world.waves.filter((_, i) => half == null || i % 2 === half).map(([lon, lat], i) => new Graphic({ geometry: geo(lon, lat), attributes: { oid: i + 1 } })),
    renderer: { type: "simple", symbol: waveSym(native) } });
}

/* Guests: one feature per city & side. Renderer, size variable, labels, popup and legend all come from the layer. */
export function guestLayer(flows) {
  return clientLayer({
    title: "Our guests", geometryType: "point", legendEnabled: true, popupEnabled: true, outFields: ["*"],
    fields: fields(["fid", "integer"], ["city", "string"], ["country", "string"], ["side", "string"], ["guests", "integer"], ["km", "double"]),
    source: flows.map(f => new Graphic({ geometry: geo(f.o.lon, f.o.lat),
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
      content: ({ graphic }) => {
        const f = flows[graphic.attributes.fid], s = SIDES[f.o.side];
        const ICON = { Plane: "✈", Car: "🚗", Train: "🚆" };
        const el = document.createElement("div");
        el.className = "guest-card";
        // the popup renders inside shadow DOM, so the card carries its own inline styles
        el.innerHTML = `
          <div style="font:500 9px Inter,sans-serif;letter-spacing:.24em;text-transform:uppercase;color:${s.color}">${esc(s.label)} · ${esc(f.o.country)}</div>
          <div style="font:400 34px/1 'Instrument Serif',serif;color:#c2541f;margin:6px 0 4px">${fmt(f.km)} km</div>
          <div style="font:400 12px/1.55 Inter,sans-serif;color:#4a3b2f">${f.o.guests} guest${f.o.guests > 1 ? "s" : ""} on their way to the Algarve
            &nbsp;·&nbsp; ${Object.entries(f.o.modes).map(([m, n]) => `${ICON[m] || ""} ${n}`).join(" &nbsp; ")}<br>
            ${f.o.parties.slice(0, 3).map(p => esc(p.party_lead)).join(", ")}${f.o.parties.length > 3 ? ` + ${f.o.parties.length - 3} more` : ""}</div>
          ${f.o.note ? `<div style="font:italic 400 19px/1.2 'Instrument Serif',serif;color:#1e4bb8;margin-top:8px">“${esc(f.o.note)}”</div>` : ""}`;
        return el;
      },
    },
  });
}
