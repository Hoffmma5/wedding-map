# Azulejo basemap (Web Mercator)

A hand-inked, tile-inspired world basemap built from the same cartography as the wedding map:
cream land, cobalt ink coast that wanders off the land like hand-inking, soft coastal water lines,
and a calmer generalization at small scales. Data: Natural Earth 1:50m (public domain).

## Build

```bash
python scripts/basemap_data.py
"C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe" scripts\basemap_pro.py --vtpk
```

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
