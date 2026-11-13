"""Prepare the "Azulejo Algarve" large-scale basemap (1:2M down to street level) from OpenStreetMap.

Run scripts/algarve_fetch.py first (Overpass downloads in data-raw/osm/). Writes Esri JSON in Web Mercator to
basemap/algarve/*.json for scripts/algarve_pro.py. Data © OpenStreetMap contributors, ODbL 1.0.

Land comes from the OSM coastline (lines with the land on their left): polygonized against the frame, each face is
land or sea by the direction of the coastline along it. The coast is generalized in three zoom bands, each with its
own hand-inked copy (the same idea as the world basemaps: ink = land ∪ a coarser smoothed copy, wedges = ink − land),
with the ink's wobble scaled to the band so it stays subtle at street level.
"""
import json
from collections import Counter, defaultdict
import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import linemerge, polygonize, unary_union

from generalize import ROOT, chaikin

RAW = ROOT / "data-raw/osm"
OUT = ROOT / "basemap/algarve"
OUT.mkdir(parents=True, exist_ok=True)
TO_M = Transformer.from_crs(4326, 3857, always_xy=True)


def merc(g):
    return shapely.transform(g, lambda xy: np.column_stack(TO_M.transform(xy[:, 0], xy[:, 1])))


def bbox_m(s, w, n, e):
    (x0, x1), (y0, y1) = TO_M.transform([w, e], [s, n])
    return box(x0, y0, x1, y1)


CONTEXT = bbox_m(35.00, -11.50, 40.00, -4.50)
MID = bbox_m(36.55, -9.70, 38.75, -6.60)
DETAIL = bbox_m(36.90, -9.05, 38.35, -7.25)   # the Algarve and south Alentejo: no gap in the 1:2M view


def load(name):
    return json.load(open(RAW / f"{name}.json", encoding="utf-8"))["elements"]


def way_line(el):
    pts = [(p["lon"], p["lat"]) for p in el.get("geometry", []) if p]
    return LineString(pts) if len(pts) >= 2 else None


def area_geom(el):
    """closed way → polygon; multipolygon relation → outer rings minus inner rings; osmium area → WKT"""
    if el["type"] == "wkt":
        return shapely.from_wkt(el["wkt"]).buffer(0)
    if el["type"] == "way":
        pts = [(p["lon"], p["lat"]) for p in el.get("geometry", []) if p]
        if len(pts) >= 4 and pts[0] == pts[-1]:
            return Polygon(pts).buffer(0)
        return None
    outer, inner = [], []
    for m in el.get("members", []):
        if m.get("type") != "way" or not m.get("geometry"): continue
        line = LineString([(p["lon"], p["lat"]) for p in m["geometry"] if p])
        (inner if m.get("role") == "inner" else outer).append(line)
    if not outer: return None
    polys = lambda lines: unary_union(list(polygonize(linemerge(unary_union(lines))))) if lines else Polygon()
    g = polys(outer)
    return g.difference(polys(inner)).buffer(0) if inner else g.buffer(0)


# ---- Esri JSON output ----------------------------------------------------------------------------------------------
FIELD = {str: "esriFieldTypeString", int: "esriFieldTypeInteger", float: "esriFieldTypeDouble"}


def esri_geom(g):
    if g.geom_type in ("Polygon", "MultiPolygon"):
        rings = []
        for p in getattr(g, "geoms", [g]):
            p = orient(p, sign=-1.0)
            rings.append([[round(x, 1), round(y, 1)] for x, y in p.exterior.coords])
            rings += [[[round(x, 1), round(y, 1)] for x, y in i.coords] for i in p.interiors]
        return {"rings": rings}
    if g.geom_type in ("LineString", "MultiLineString"):
        return {"paths": [[[round(x, 1), round(y, 1)] for x, y in l.coords] for l in getattr(g, "geoms", [g])]}
    return {"x": round(g.x, 1), "y": round(g.y, 1)}


def save(name, items, kind):
    """items: (geometry in Web Mercator, {attributes})"""
    gt = {"polygon": "esriGeometryPolygon", "line": "esriGeometryPolyline", "point": "esriGeometryPoint"}[kind]
    attrs = items[0][1] if items else {}
    fields = [{"name": "OBJECTID", "type": "esriFieldTypeOID"}] + [{"name": k, "type": FIELD[type(v)], **({"length": 120} if isinstance(v, str) else {})} for k, v in attrs.items()]
    feats = [{"attributes": {"OBJECTID": i + 1, **a}, "geometry": esri_geom(g)} for i, (g, a) in enumerate(items) if not g.is_empty]
    doc = {"geometryType": gt, "spatialReference": {"wkid": 102100, "latestWkid": 3857}, "fields": fields, "features": feats}
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"  {name:<22} {len(feats):>6} features  {path.stat().st_size / 1e6:6.1f} MB")


def parts(g):
    return [p for p in getattr(g, "geoms", [g]) if not p.is_empty]


# ---- the ink look for every line and area: simplify, then round the corners (Chaikin) --------------------------------
def key(xy):
    return (round(xy[0], 1), round(xy[1], 1))


def smooth_lines(items, tol=3.0):
    """Smooth a network of lines without pulling junctions apart: every line is split at the vertices it shares with
    another line (and at its ends), and each piece is smoothed with its end points fixed."""
    count = Counter(key(c) for g, _ in items for c in g.coords)
    out = []
    for g, a in items:
        coords = list(g.coords)
        cut = [0] + [i for i in range(1, len(coords) - 1) if count[key(coords[i])] > 1] + [len(coords) - 1]
        for i0, i1 in zip(cut, cut[1:]):
            piece = coords[i0:i1 + 1]
            if len(piece) >= 3:
                piece = list(LineString(piece).simplify(tol).coords)
                piece = chaikin(piece, 2, closed=False)
                piece = list(LineString(piece).simplify(tol * 0.15).coords)
            if len(piece) >= 2:
                out.append((LineString(piece), a))
    return out


def smooth_area(p):
    """simplify by a tolerance that grows with the area's size, then two rounds of corner cutting"""
    tol = min(15.0, max(1.5, p.area ** 0.5 / 150))
    s = p.simplify(tol, preserve_topology=True)
    res = []
    for q in parts(s):
        if q.geom_type != "Polygon": continue
        r = Polygon(chaikin(list(q.exterior.coords), 2, True), [chaikin(list(i.coords), 2, True) for i in q.interiors]).buffer(0)
        res.append(r.simplify(tol * 0.2, preserve_topology=True))
    return unary_union(res) if res else Polygon()


def by_area(a, steps):
    """zoom level from an area (m², Web Mercator): steps = [(min area, zoom), …] from large to small"""
    for threshold, z in steps:
        if a >= threshold: return z
    return steps[-1][1]


# ---- land from the coastline ----------------------------------------------------------------------------------------
def build_land():
    lines = [merc(l) for l in (way_line(el) for el in load("coastline")) if l is not None]
    coast = unary_union(lines).intersection(CONTEXT)
    noded = unary_union([coast, CONTEXT.exterior])
    faces = list(polygonize(noded))
    # direction of every coastline segment: land lies on its left
    seg_dir = {}
    for l in lines:
        c = list(l.coords)
        for a, b in zip(c, c[1:]):
            seg_dir[(round(a[0], 2), round(a[1], 2), round(b[0], 2), round(b[1], 2))] = 1
    land = []
    for f in faces:
        f = orient(f, sign=1.0)          # counter-clockwise: the interior is on the left of the boundary
        votes = 0
        c = list(f.exterior.coords)
        for a, b in zip(c, c[1:]):
            k = (round(a[0], 2), round(a[1], 2), round(b[0], 2), round(b[1], 2))
            if k in seg_dir: votes += 1          # coast runs with the boundary: the face is on the coast's left = land
            elif (k[2], k[3], k[0], k[1]) in seg_dir: votes -= 1
        if votes > 0: land.append(f)
    return unary_union(land).buffer(0)


def soft(poly, tol, iterations=2, thin=0.3):
    s = poly.simplify(tol, preserve_topology=True)
    out = []
    for p in parts(s):
        if p.geom_type != "Polygon": continue
        q = Polygon(chaikin(list(p.exterior.coords), iterations, True), [chaikin(list(i.coords), iterations, True) for i in p.interiors]).buffer(0)
        out.append(q.simplify(tol * thin, preserve_topology=True))
    return unary_union(out)


def ink_band(land, tol, ink_tol, min_area):
    """-> land (generalized), coast outline (ink ∪ land), wedges (ink outside the land), water-line outline"""
    g = unary_union([p for p in parts(soft(land, tol)) if p.area >= min_area])
    loose = soft(g, ink_tol)
    inked = unary_union([g, loose])
    wedges = inked.difference(g)
    wedges = unary_union([p for p in parts(wedges) if p.geom_type == "Polygon" and p.area > (tol * 0.5) ** 2])
    return g, inked, wedges, inked.simplify(tol * 0.6, preserve_topology=True)


BANDS = [   # name, zoom from, frame, next frame, simplify (m), ink wobble (m), smallest island (m²)
    ("b1", 8, CONTEXT, MID, 250, 700, 4e6),
    ("b2", 11, MID, DETAIL, 40, 140, 1.5e5),
    ("b3", 14, DETAIL, None, 6, 12, 2e3),   # street level: a wobble of metres, not tens of metres
]


def write_bands(land):
    for name, z, frame, nxt, tol, ink_tol, min_area in BANDS:
        g, inked, wedges, ripple = ink_band(land.intersection(frame.buffer(5000)), tol, ink_tol, min_area)
        # the ink and the water lines are the coastline itself, as lines: clipping a polygon outline to the band's frame
        # would also draw the frame's straight edges across land and sea
        for layer, geom, kind in (("land", g, "polygon"), ("ink", inked.boundary, "line"), ("wedges", wedges, "polygon"),
                                  ("ripple", ripple.boundary, "line")):
            pieces = []
            if nxt is None:
                pieces.append((geom.intersection(frame), "all"))
            else:   # inside the next frame only until the next band takes over; outside it, at every larger scale
                pieces.append((geom.intersection(nxt), "inner"))
                pieces.append((geom.difference(nxt), "outer"))
            ok = ("Polygon", "MultiPolygon") if kind == "polygon" else ("LineString", "MultiLineString")
            items = [(p, {"part": part, "band": name}) for g2, part in pieces for p in parts(g2) if p.geom_type in ok]
            save(f"{name}_{layer}", items, kind)


# ---- everything else ------------------------------------------------------------------------------------------------
ROAD_ZOOM = {"motorway": 8, "trunk": 8, "primary": 9, "secondary": 10, "tertiary": 11, "motorway_link": 11, "trunk_link": 11,
             "primary_link": 12, "secondary_link": 12, "tertiary_link": 13, "unclassified": 13, "residential": 13,
             "living_street": 14, "pedestrian": 14}
ROAD_CLASS = {"motorway": "motorway", "trunk": "motorway", "motorway_link": "motorway", "trunk_link": "motorway",
              "primary": "primary", "primary_link": "primary", "secondary": "secondary", "secondary_link": "secondary",
              "tertiary": "tertiary", "tertiary_link": "tertiary"}


def roads():
    items = []
    for el in load("roads"):
        t = el.get("tags", {}); hw = t.get("highway")
        l = way_line(el)
        if l is None or hw not in ROAD_ZOOM: continue
        g = merc(l).intersection(DETAIL)
        for p in parts(g):
            if p.geom_type != "LineString": continue
            items.append((p, {"cls": ROAD_CLASS.get(hw, "minor"), "min_zoom": ROAD_ZOOM[hw], "label": t.get("name") or "", "ref": t.get("ref") or ""}))
    for el in load("context_roads"):   # motorways beyond the Algarve for the 1:2M views
        l = way_line(el)
        if l is None: continue
        g = merc(l).intersection(CONTEXT).difference(DETAIL.buffer(-1))
        for p in parts(g):
            if p.geom_type == "LineString":
                items.append((p, {"cls": "motorway", "min_zoom": 8, "label": "", "ref": el.get("tags", {}).get("ref") or ""}))
    save("roads", smooth_lines(items), "line")
    rails = [(p, {"label": ""}) for el in load("railways") for l in [way_line(el)] if l for p in parts(merc(l).intersection(DETAIL)) if p.geom_type == "LineString"]
    save("railways", smooth_lines(rails, tol=5.0), "line")


PLACE_ZOOM = {"city": 8, "town": 9, "village": 11, "suburb": 13, "hamlet": 13, "neighbourhood": 15, "locality": 15, "island": 12}


def places():
    items = []
    seen = set()
    sources = [("places", DETAIL)] + ([("context_places", CONTEXT)] if (RAW / "context_places.json").exists() else [])
    for src, frame in sources:
        for el in load(src):
            t = el.get("tags", {}); kind = t.get("place"); name = t.get("name")
            if not name or kind not in PLACE_ZOOM or (name, kind) in seen: continue
            p = merc(Point(el["lon"], el["lat"]))
            if not frame.contains(p): continue
            seen.add((name, kind))
            try: pop = int(str(t.get("population", "0")).replace(" ", "").replace(".", "").replace(",", ""))
            except ValueError: pop = 0
            items.append((p, {"label": name, "kind": kind, "min_zoom": PLACE_ZOOM[kind], "pop": pop}))
    if len(sources) == 1:   # towns beyond the Algarve for the 1:2M views: Natural Earth's populated places
        ne = json.load(open(ROOT / "data-raw/ne/ne_10m_populated_places_simple.geojson", encoding="utf-8"))["features"]
        for f in ne:
            pr = f["properties"]; lon, lat = f["geometry"]["coordinates"]
            p = merc(Point(lon, lat))
            if not CONTEXT.contains(p) or DETAIL.contains(p) or (pr.get("min_zoom") or 9) > 7: continue
            items.append((p, {"label": pr.get("nameascii") or pr.get("name"), "kind": "city" if (pr.get("pop_max") or 0) > 300_000 else "town",
                              "min_zoom": 8 if (pr.get("pop_max") or 0) > 300_000 else 9, "pop": int(pr.get("pop_max") or 0)}))
    items.sort(key=lambda it: (it[1]["min_zoom"], -it[1]["pop"]))
    save("places", items, "point")
    peaks = []
    for el in load("peaks"):
        t = el.get("tags", {})
        ele = t.get("ele", "").split(";")[0].replace(",", ".").strip()
        label = f"{t['name']} {round(float(ele))} m" if ele.replace(".", "", 1).isdigit() else t["name"]
        peaks.append((merc(Point(el["lon"], el["lat"])), {"label": label}))
    save("peaks", peaks, "point")


def areas(src, attrs_of, min_area, frame=DETAIL):
    items = []
    for el in load(src):
        g = area_geom(el)
        if g is None or g.is_empty: continue
        g = merc(g).intersection(frame)
        a = attrs_of(el.get("tags", {}), g)
        if a is None: continue
        for p in parts(g):
            if p.geom_type in ("Polygon", "MultiPolygon") and p.area >= min_area:
                s = smooth_area(p)
                if not s.is_empty:
                    items.append((s, {**a, "min_zoom": a["zoom_of"](p.area)} if "zoom_of" in a else a))
    for _, a in items: a.pop("zoom_of", None)
    return items


# zoom levels by size: small things only appear when there is room for them (no speckle of ponds and bits of wood)
WATER_ZOOM = [(1.5e7, 8), (2e6, 10), (3e5, 12), (5e4, 14), (1e4, 15), (0, 16)]   # big reservoirs from zoom 8, with their rivers
WET_ZOOM = [(1e6, 10), (1e5, 12), (1e4, 14), (0, 15)]
BEACH_ZOOM = [(2e5, 11), (2e4, 13), (0, 14)]
WOOD_ZOOM = [(3e6, 11), (3e5, 13), (5e4, 14), (0, 15)]
PARK_ZOOM = [(2e5, 12), (2e4, 14), (0, 15)]


def water_and_land_cover(land3):
    RIVER_BED = ("river", "canal", "stream", "oxbow", "rapids")
    water = areas("water", lambda t, g: {"label": t.get("name") or "", "kind": "river" if t.get("water") in RIVER_BED else "lake",
                                         "zoom_of": lambda a: by_area(a, WATER_ZOOM)}, 500)
    save("water", water, "polygon")
    # beaches are drawn on top of the sea too (sandbanks), but only where OSM maps them
    save("beaches", areas("beaches", lambda t, g: {"label": t.get("name") or "", "zoom_of": lambda a: by_area(a, BEACH_ZOOM)}, 200), "polygon")

    def wet_attrs(t, g):
        kind = t.get("wetland", "")
        cls = "tidal" if kind in ("tidalflat", "saltmarsh", "saltern", "mangrove") else "marsh"
        return {"cls": cls, "zoom_of": lambda a: by_area(a, WET_ZOOM)}
    save("wetlands", areas("wetlands", wet_attrs, 2000), "polygon")

    def green_attrs(t, g):
        if t.get("leisure") == "golf_course": return {"cls": "golf", "label": t.get("name") or "", "min_zoom": 11}
        if t.get("leisure") in ("park", "nature_reserve"): return {"cls": "park", "label": t.get("name") or "", "zoom_of": lambda a: by_area(a, PARK_ZOOM)}
        return {"cls": "wood", "label": t.get("name") or "", "zoom_of": lambda a: by_area(a, WOOD_ZOOM)}
    save("greens", areas("greens", green_attrs, 2000), "polygon")

    # rivers and streams: cut where they run through a lake or reservoir (the water body is drawn instead), smoothed;
    # rivers appear by their total length, streams only close in, very short ones not at all
    lakes = [g for g, a in water if a["kind"] == "lake"]   # not the river's own bed (water=river), or the river would break up
    tree = shapely.STRtree(lakes)
    lines = []
    for el in load("waterways"):
        t = el.get("tags", {}); l = way_line(el)
        if l is None: continue
        ww = t.get("waterway")
        for p in parts(merc(l).intersection(DETAIL)):
            if p.geom_type != "LineString": continue
            hits = [lakes[i] for i in tree.query(p, predicate="intersects")]
            if hits: p = p.difference(unary_union(hits))
            for q in parts(p):
                if q.geom_type == "LineString" and q.length > 30:
                    lines.append((q, {"cls": "river" if ww == "river" else "stream", "label": t.get("name") or "", "min_zoom": 0}))
    total = defaultdict(float)
    for g, a in lines:
        if a["cls"] == "river" and a["label"]: total[a["label"]] += g.length
    for g, a in lines:
        if a["cls"] == "river":
            n = total.get(a["label"], 0)
            a["min_zoom"] = 8 if n > 40e3 else 10 if n > 10e3 else 12
        else:
            a["min_zoom"] = 15 if g.length > 600 else 16
    lines = [(g, a) for g, a in lines if not (a["cls"] == "stream" and g.length < 150)]
    save("waterways", smooth_lines(lines), "line")


if __name__ == "__main__":
    print("land"); land = build_land()
    print(f"  land area {land.area / 1e6:,.0f} km² (Web Mercator)")
    print("bands"); write_bands(land)
    print("roads"); roads()
    print("places"); places()
    print("water & land cover"); water_and_land_cover(land)
    save("sea", [(CONTEXT, {"label": ""})], "polygon")
    # country borders for the overview scales (Natural Earth 1:10m; closer in, the Guadiana shows the border itself)
    ne = json.load(open(ROOT / "data-raw/ne/ne_10m_admin_0_boundary_lines_land.geojson", encoding="utf-8"))["features"]
    borders = []
    for f in ne:
        g = merc(shapely.geometry.shape(f["geometry"])).intersection(CONTEXT)
        borders += [(p, {"label": ""}) for p in parts(g) if p.geom_type == "LineString"]
    save("borders", borders, "line")
