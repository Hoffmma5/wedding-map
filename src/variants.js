/* Design variants, chosen in the URL hash, e.g.
     #proj=aeqd&sea=contours+currents&land=relief&rim=tiles&flows=arrive
   Every axis is independent, so looks can be mixed and matched. The "Design" panel edits the hash and reloads. */

export const AXES = {
  proj:  { label: "Projection", options: { laea: "Equal-area", aeqd: "Equidistant" } },
  sea:   { label: "Sea", multi: true, options: { waves: "Waves", contours: "Depth lines", currents: "Currents" } },
  land:  { label: "Land", options: { sage: "Sage", apricot: "Apricot", relief: "Blue relief", azulejo: "Azulejo" } },
  rim:   { label: "Rim", options: { simple: "Simple", tiles: "Tiles" } },
  flows: { label: "Flows", options: { loop: "Looping dots", arrive: "Arrive & rest" } },
};

export const ORIGINAL = { proj: "laea", sea: ["waves"], land: "sage", rim: "simple", flows: "loop" };
// Marek's picks (Nov 2026): equidistant plate, faint currents, azulejo land, tile rim, arrive & rest
export const DEFAULT = { proj: "aeqd", sea: ["currents"], land: "azulejo", rim: "tiles", flows: "arrive" };

function parse() {
  const raw = location.hash.replace(/^#/, "");
  const q = new URLSearchParams(raw === "cim" ? "cim=1" : raw);
  const v = structuredClone(DEFAULT);
  if (q.get("preset") === "original") Object.assign(v, structuredClone(ORIGINAL));
  for (const [k, ax] of Object.entries(AXES)) {
    if (!q.has(k)) continue;
    const val = q.get(k);
    if (ax.multi) v[k] = val.split(/[+, ]/).filter(x => x in ax.options);
    else if (val in ax.options) v[k] = val;
  }
  v.cim = q.has("cim");   // native CIM symbol animations (experimental)
  return v;
}

export const VARIANT = parse();

export function hashFor(v) {
  const parts = Object.keys(AXES).map(k => `${k}=${Array.isArray(v[k]) ? (v[k].join("+") || "none") : v[k]}`);
  if (v.cim) parts.push("cim");
  return "#" + parts.join("&");
}

/** Builds the Calcite controls of the Design panel; changing anything reloads with the new hash. */
export function buildPanel(el) {
  const go = v => { location.hash = hashFor(v); location.reload(); };
  const rows = Object.entries(AXES).map(([k, ax]) => {
    const items = Object.entries(ax.options).map(([val, label]) => {
      const on = ax.multi ? VARIANT[k].includes(val) : VARIANT[k] === val;
      return ax.multi
        ? `<calcite-chip value="${val}" ${on ? "selected" : ""} scale="s">${label}</calcite-chip>`
        : `<calcite-segmented-control-item value="${val}" ${on ? "checked" : ""}>${label}</calcite-segmented-control-item>`;
    }).join("");
    return `<div class="axis"><div class="caps">${ax.label}</div>${ax.multi
      ? `<calcite-chip-group data-axis="${k}" selection-mode="multiple" label="${ax.label}">${items}</calcite-chip-group>`
      : `<calcite-segmented-control data-axis="${k}" scale="s" width="full">${items}</calcite-segmented-control>`}</div>`;
  }).join("");
  el.innerHTML = `${rows}<div class="presets">
      <calcite-button id="pOriginal" appearance="outline" scale="s">Original</calcite-button>
      <calcite-button id="pDefault" scale="s">Default</calcite-button></div>`;
  el.querySelectorAll("calcite-segmented-control").forEach(c => c.addEventListener("calciteSegmentedControlChange", () => go({ ...VARIANT, [c.dataset.axis]: c.value })));
  el.querySelectorAll("calcite-chip-group").forEach(c => c.addEventListener("calciteChipGroupSelect", () => go({ ...VARIANT, [c.dataset.axis]: c.selectedItems.map(i => i.value) })));
  el.querySelector("#pOriginal").addEventListener("click", () => go({ ...ORIGINAL, cim: VARIANT.cim }));
  el.querySelector("#pDefault").addEventListener("click", () => go({ ...DEFAULT, cim: VARIANT.cim }));
}
