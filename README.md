# Everyone's coming to the Algarve

Interactive origin–destination flow map of wedding guests, built with the
ArcGIS Maps SDK for JavaScript (map components + `@arcgis/core`) and Calcite, bundled with Vite.

```bash
npm install
npm run dev       # http://localhost:5173  (add #cim to try native CIM symbol animations)
npm run build     # static site in dist/ (relative paths, host anywhere)
```

## Layout
- `index.html`: page shell (title card, controls, stats) with slotted map components
- `src/config.js`: venue, sides (labels/colours), palette, data URLs
- `src/projection.js`: venue-centred Lambert azimuthal equal-area (custom WKT) + `laea()`, `kmTo()`
- `src/data.js`: runtime loading of `public/data/rsvps.csv` and `public/data/world.json`
- `src/layers.js`: plate, graticule, waves, coastal water lines, countries, guests (renderer, labels, popup)
- `src/main.js`: map component setup, flow animation, replay and guest tour
- `scripts/rsvp.py`: generates simulated RSVPs → `public/data/rsvps.csv`
- `scripts/world.py`: builds `public/data/world.json` from Natural Earth 1:50m (`world-atlas`, installed as a devDependency); needs shapely + pyproj
- `legacy/wedding-flow-map.html`: the single-file version this was ported from (for comparison)
