# Everyone's coming to the Algarve

Interactive origin–destination flow map of wedding guests, built with the
ArcGIS Maps SDK for JavaScript (map components + `@arcgis/core`) and Calcite, bundled with Vite.

```bash
npm install
npm run dev       # http://localhost:5173
npm run build     # static site in dist/ (relative paths, host anywhere)
```

## Design variants
The palette button (top right) opens a Design panel; each choice is stored in the URL hash, so looks can be
shared and compared, e.g. `#proj=aeqd&sea=contours+currents&land=relief&rim=tiles&flows=arrive`.

| axis | options |
|---|---|
| `proj` | `laea` equal-area (original) · `aeqd` equidistant: straight line from the venue = true route and distance |
| `sea` (combinable) | `waves` (original) · `contours` depth lines (ETOPO1) · `currents` NOAA surface currents with the SDK FlowRenderer |
| `land` | `sage` (original) · `apricot` light orange + cobalt hillshade · `relief` sage + cobalt hillshade · `azulejo` cream land, cobalt relief and elevation lines |
| `rim` | `simple` (original) · `tiles` azulejo tile band with a rope moulding (CIM) |
| `flows` | `loop` dots circulate forever (original) · `arrive` each route draws once, a traveller lands with a ripple; hover/click a city to send one again |

Default (no hash): `proj=aeqd&sea=currents&land=azulejo&rim=tiles&flows=arrive`. `#preset=original` restores the first version; add `&cim` to try native CIM symbol animations.

Hovering a city or its route highlights it, sends a traveller and opens the guest card (tap on phones).
`npm run serve-prod` builds and serves the production bundle on :4173; add `?timing` to log first-draw times.

## Layout
- `index.html`: page shell (title card, controls, stats) with slotted map components
- `src/variants.js`: design variants (URL hash) and the Design panel
- `src/config.js`: venue, sides (labels/colours), palette, data URLs
- `src/projection.js`: venue-centred Lambert azimuthal equal-area (custom WKT) + `laea()`, `kmTo()`
- `src/data.js`: runtime loading of `public/data/rsvps.csv` and `public/data/world.json`
- `src/layers.js`: plate, graticule, waves, coastal water lines, countries, guests (renderer, labels, popup)
- `src/main.js`: map component setup, flow animation, replay and guest tour
- `scripts/rsvp.py`: generates simulated RSVPs → `public/data/rsvps.csv`
- `scripts/terrain.py`: contours + per-projection relief images from ETOPO1 (download URL in the script)
- `scripts/currents.py`: NOAA AOML surface currents → `public/data/currents.json` (download URL in the script)
- `scripts/world.py`: builds `public/data/world.json` from Natural Earth 1:50m (`world-atlas`, installed as a devDependency); needs shapely + pyproj; the other scripts need numpy, scipy, matplotlib (contourpy), pillow
- `legacy/wedding-flow-map.html`: the single-file version this was ported from (for comparison)
