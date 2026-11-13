# Azulejo basemap (Web Mercator)

A hand-inked, tile-inspired world basemap built from the same cartography as the wedding map:
cream land, cobalt ink coast that wanders off the land like hand-inking, soft coastal water lines,
and a calmer generalization at small scales. Data: Natural Earth 1:50m (public domain).

Two versions are built from the same project:

- **Azulejo** (`Azulejo.vtpk`): land, ink coast, water lines, borders. A decorative base.
- **Azulejo atlas** (`Azulejo_Atlas.vtpk`): the same, plus inked rivers and lakes, cities, and labels for countries,
  cities, oceans, seas, lakes and rivers, each appearing at the zoom level Natural Earth recommends. Borders are dashed
  in the atlas so they never get confused with rivers.

## Build

```bash
python scripts/basemap_data.py
python scripts/atlas_data.py
"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" scripts\basemap_pro.py --vtpk
```

`atlas_data.py` needs these Natural Earth GeoJSON files in `data-raw/ne/` (from
https://github.com/nvkelso/natural-earth-vector/tree/master/geojson): `ne_50m_rivers_lake_centerlines_scale_rank`,
`ne_50m_lakes`, `ne_10m_populated_places_simple`, `ne_50m_admin_0_countries`, `ne_50m_geography_marine_polys`.
Add `--atlas-only` to build just the atlas.

### Label font

The labels are meant to be set in **Instrument Serif** (the wedding map's title font, SIL Open Font License, so it may
be embedded in a public basemap; the license is in `InstrumentSerif-OFL.txt`). A vector tile package embeds the glyphs of
the fonts it uses, so Pro must be able to load the font. On machines with the Windows "block untrusted fonts" policy,
only fonts installed **for all users** (`C:\Windows\Fonts`) can be loaded: right-click the `.ttf` files → *Install for
all users* (needs admin rights), then rebuild with:

```bash
"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" scripts\basemap_pro.py --atlas-only --vtpk --font="Instrument Serif"
```

Until then the atlas uses **Avenir Next LT Pro**, which ships with ArcGIS Pro for use in maps and vector tiles.

| Atlas layer | Appears from web zoom | Style |
|---|---|---|
| Oceans | 1 | italic spaced capitals, cobalt |
| Seas, gulfs, straits | 3 / 5 / 6 | italic, cobalt |
| Countries | 2–5 (Natural Earth `MIN_LABEL`) | spaced capitals, cobalt; large countries bigger |
| Cities | 3–7 (Natural Earth `min_zoom`) | cream dot with a cobalt ring; ink-dark names, capitals larger |
| Rivers | 2–6 | cobalt ink, 1.8 → 0.95 px; italic names along the river from zoom 4 / 6 |
| Lakes | 2 / 4 / 5 | sea fill, inked shore; italic names from zoom 5 |

1. `basemap_data.py` (shapely) writes `basemap/data/*.geojson`: the whole world evenly generalized, split at the
   date line, Antarctica included, clipped to ±85.05°.
2. `basemap_pro.py` (arcpy) builds `Azulejo.gdb` (Web Mercator), `Azulejo.aprx` with the styled map
   "Azulejo basemap", `preview_*.png`, and with `--vtpk` the vector tile package `Azulejo.vtpk`
   (ArcGIS Online tiling scheme, zoom 1–9; vector tiles overzoom nicely beyond that).

Open `Azulejo.aprx` in ArcGIS Pro to tweak symbols or scale ranges, then run *Create Vector Tile Package*
on the map again (or rerun the script).

## Publish on ArcGIS Online

1. **Content → New item →** drop `Azulejo.vtpk`, keep **"Create a hosted vector tile layer"** ticked.
2. In the new tile layer's item page: add a description, set **Credits** to
   `Natural Earth; cartography: Marek Hoffmann`, then **Share → Everyone**.
3. To use it as a basemap: open it in Map Viewer, then on the layer choose **Move to basemap**
   (or add the layer to your organization's basemap gallery group).
4. Colours can be changed later without rebuilding, in the **Vector Tile Style Editor**.

## How the look is made

| Layer (top → bottom) | Data | Symbol |
|---|---|---|
| Countries / Land (small scale) | land, smoothed | cream fill, borders cobalt 50 % at 0.5 px |
| Ink wedges | where the ink copy lies outside the land | cobalt fill |
| Coast ink | land ∪ a coarser smoothed copy of it | 1.8 px cobalt stroke, no fill (the land covers its inner half) |
| Water lines | the coast, lighter | per ring: sea-coloured stroke on a slightly wider faint-cobalt stroke |
| Graticule, ocean | 15° lines, world box | cobalt 10 %, sea fill |

- **Topology-aware smoothing**: every shared border arc of the TopoJSON is simplified (Douglas-Peucker 0.02°)
  and smoothed (two rounds of Chaikin corner cutting) once, so neighbours stay identical, with no slivers.
- **The ink**: the dissolved land is simplified again a bit coarser (0.03°) and smoothed. The union of land and
  that copy is drawn as a stroke under the land, so the ink always sits on or outside the coast. Where the hand
  "strays" out to sea, the wedge between them is filled with ink and reads as a thicker brush stroke.
- **Small scales** (zoom 0–3): the dissolved land is closed (grown and shrunk by 0.06°) to fill fjords, small
  islands are dropped, and borders become separate lines clipped to that land.
- **Water lines by scale**: 1 ring at zoom 0–3, 2 rings at zoom 4–5, 3 rings from zoom 6.
- Not included (they are not vector data): the cobalt hillshade relief and the animated ocean currents of the
  web map. The relief could be added as a separate hillshade tile layer.

## Azulejo Algarve (large scale)

A third package for maps around the venue: **`Azulejo_Algarve.vtpk`**, web zoom 8 (1:2.3M) down to 17 (1:4.5k,
street level; vector tiles overzoom sharply beyond). Same style, from OpenStreetMap data.

```bash
curl -L -o data-raw/pbf/portugal-latest.osm.pbf https://download.geofabrik.de/europe/portugal-latest.osm.pbf
python scripts/algarve_pbf.py      # filters the Algarve out of the extract (+ one small Overpass query for the Spanish bank)
python scripts/algarve_data.py     # land, inked coast in three zoom bands, roads, water, beaches, greens, places
"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" scripts\algarve_pro.py --vtpk
```

`scripts/algarve_fetch.py` gets the coastline and the context motorways (south Portugal, Andalusia, north Morocco)
from Overpass, tile by tile, and can fetch everything else too when Overpass is not overloaded.

- **Coast**: land is built from the OSM coastline (land lies left of it) and generalized in three bands: zoom 8–10
  (~250 m, whole context), 11–13 (~40 m, around the Algarve), 14+ (~6 m, the Algarve). Each band keeps showing
  outside the next band's frame, so panning away at a large zoom never shows an empty sea. The inked copy wobbles by
  700 / 140 / 12 m, so the hand-drawn look stays subtle at street level. Ink and water lines are lines (the coast),
  not polygon outlines, so the band frames never show.
- **Roads**: motorways in terracotta, the rest white with fine cobalt casings, appearing by class
  (motorway 8, primary 9, secondary 10, tertiary 11, minor 13) and widening in steps at zoom 11, 14 and 15.
- **Land cover**: beaches in sand, golf courses, parks and woods in soft sages, tidal flats and marsh, reservoirs.
- **Labels** (Instrument Serif): towns and cities in spaced cobalt capitals, villages, hamlets and neighbourhoods
  in ink, road names from zoom 13, street names from 15, river names in italics, peaks with their height.
- **Credits**: *© OpenStreetMap contributors (ODbL); Natural Earth*. OpenStreetMap data is open under the ODbL: keep
  the attribution on any map using this basemap.

## Azulejo complete (one basemap, world to street level)

**`Azulejo_Complete.vtpk`** merges the atlas and the Algarve into one package: the world atlas (Natural Earth) up
to web zoom 7, the Algarve and south Alentejo (OpenStreetMap) from zoom 8 (1:2.3M) to street level.

```bash
"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" scripts\complete_pro.py --vtpk
```

(after the atlas and Algarve data and geodatabases are built, see above). The switch at zoom 8 is harmonized:
the same cream, inked coast and three water lines on both sides, the same dashed borders, town names in the same
type, and the main rivers continue from the atlas into the detailed data.

Large-scale cartography in the Algarve layers:

- **Everything smoothed** like the ink coast: roads, rivers, lakes, beaches, wetlands, parks and woods are simplified
  and their corners rounded (Chaikin). Roads and rivers are split at their junctions first, so junctions stay exact.
- **Rivers end at the shore** of the lakes and reservoirs they flow through (their centrelines are cut there), and water
  bodies are drawn above rivers. A river's own mapped bed (water=river) does not cut it.
- **Size decides the zoom**: lakes and ponds appear at zoom 10 / 12 / 14 / 15 / 16 by area, woods, parks, beaches and
  wetlands likewise; streams only from zoom 15 (short ones from 16, very short ones never); rivers by their total
  length (zoom 8 / 10 / 12).
- **Detail area**: the Algarve and south Alentejo up to 38.35°N (past Beja), plus the Spanish bank of the Guadiana,
  so the 1:2M view shows no gap north of the Algarve.
