"""Extra layers for the "Azulejo atlas" basemap: rivers, lakes, cities and label points (basemap/data/atlas_*.geojson).

Run after scripts/basemap_data.py (it clips rivers to that land). Source: Natural Earth (public domain), downloaded to
data-raw/ne/ from https://github.com/nvkelso/natural-earth-vector/tree/master/geojson:
  ne_50m_rivers_lake_centerlines_scale_rank, ne_50m_lakes, ne_10m_populated_places_simple,
  ne_50m_admin_0_countries, ne_50m_geography_marine_polys
Every feature keeps Natural Earth's min_zoom (web-map zoom level at which it should appear) and gets a ready-made
`label` text, so the vector tiles only need plain label fields.
"""
import json

from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import polylabel, unary_union

from generalize import ROOT, chaikin

RAW = ROOT / "data-raw/ne"
OUT = ROOT / "basemap/data"
LAT = 85.0511287798
MAX_ZOOM = 7          # the atlas shows features up to web zoom 7 (the package is tiled to zoom 9)

def load(name):
    return json.load(open(RAW / f"{name}.geojson", encoding="utf-8"))["features"]

def save(name, features):
    path = OUT / f"atlas_{name}.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"atlas_{name:<16} {len(features):>5} features  {path.stat().st_size // 1024:>5} KB")

def feat(geom, **props):
    return {"type": "Feature", "properties": props, "geometry": mapping(geom)}

def zoom(p, *keys, default=9.0):
    for k in keys:
        v = p.get(k)
        if v is not None and v != -99: return float(v)
    return default

land = unary_union([shape(f["geometry"]).buffer(0) for f in json.load(open(OUT / "countries.geojson", encoding="utf-8"))["features"]])
land_ok = land.buffer(0.02)    # rivers may run to the (smoothed) coast, not beyond it

# ---- rivers: smoothed once, clipped to the land ---------------------------------------------------------------
rivers = []
for f in load("ne_50m_rivers_lake_centerlines_scale_rank"):
    p = f["properties"]
    mz = zoom(p, "min_zoom")
    if mz > MAX_ZOOM: continue
    g = shape(f["geometry"])
    for line in getattr(g, "geoms", [g]):
        pts = chaikin(list(line.coords), 1, closed=False)
        clipped = LineString(pts).intersection(land_ok)
        for seg in getattr(clipped, "geoms", [clipped]):
            if seg.geom_type == "LineString" and seg.length > 0.05:
                name = p.get("name_en") or p.get("name") or ""
                rivers.append(feat(seg, label=name, min_zoom=mz, min_label=zoom(p, "min_label", default=mz + 1),
                                   scalerank=int(p.get("scalerank") or 9), kind=p.get("featurecla") or "River"))
save("rivers", rivers)

# ---- lakes ------------------------------------------------------------------------------------------------------
lakes, lake_labels = [], []
for f in load("ne_50m_lakes"):
    p = f["properties"]
    mz = zoom(p, "min_zoom")
    if mz > MAX_ZOOM: continue
    g = shape(f["geometry"]).buffer(0)
    for poly in getattr(g, "geoms", [g]):
        if poly.area < 0.01: continue
        s = Polygon(chaikin(list(poly.exterior.coords), 1, True), [chaikin(list(i.coords), 1, True) for i in poly.interiors]).buffer(0)
        for q in getattr(s, "geoms", [s]):
            lakes.append(feat(orient(q, 1.0), label=p.get("name") or "", min_zoom=mz))
    name = p.get("name")
    if name and g.area > 0.3:
        big = max(getattr(g, "geoms", [g]), key=lambda q: q.area)
        lake_labels.append(feat(polylabel(big, 0.01), label=name, min_zoom=zoom(p, "min_label", default=mz + 1)))
save("lakes", lakes)

# ---- cities -----------------------------------------------------------------------------------------------------
cities = []
for f in load("ne_10m_populated_places_simple"):
    p = f["properties"]
    mz = zoom(p, "min_zoom")
    if mz > MAX_ZOOM: continue
    capital = 1 if p.get("adm0cap") == 1 else 0
    cities.append(feat(shape(f["geometry"]), label=p.get("nameascii") or p.get("name") or "", min_zoom=mz,
                       capital=capital, rank=int(p.get("scalerank") or 10), pop=int(p.get("pop_max") or 0)))
cities.sort(key=lambda f: (f["properties"]["min_zoom"], -f["properties"]["pop"]))   # bigger cities first
save("cities", cities)

# ---- country label points (Natural Earth's own label positions) -------------------------------------------------
countries = []
for f in load("ne_50m_admin_0_countries"):
    p = f["properties"]
    x, y = p.get("LABEL_X"), p.get("LABEL_Y")
    if x is None or y is None or abs(y) > 80: continue
    name = p.get("NAME_EN") or p.get("NAME")
    countries.append(feat(Point(x, y), label=name.upper(), min_zoom=zoom(p, "MIN_LABEL", default=4),
                          rank=int(p.get("LABELRANK") or 6)))
save("country_labels", countries)

# ---- seas and oceans: a point deep inside each water body ------------------------------------------------------
WORLD = box(-180, -LAT, 180, LAT)
marine = []
for f in load("ne_50m_geography_marine_polys"):
    p = f["properties"]
    kind = p.get("featurecla")
    if kind not in ("ocean", "sea", "gulf", "bay", "strait", "channel"): continue
    name = p.get("name_en") or p.get("name")
    if not name: continue
    g = shape(f["geometry"]).buffer(0).intersection(WORLD)
    if g.is_empty: continue
    big = max(getattr(g, "geoms", [g]), key=lambda q: q.area)
    text = name.upper() if kind == "ocean" else name
    marine.append(feat(polylabel(big, 0.05), label=text, min_zoom=zoom(p, "min_label", default=4), kind=kind))
save("marine_labels", marine)
save("lake_labels", lake_labels)
