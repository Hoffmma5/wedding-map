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
from math import cos, hypot, radians
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


# ---- small-scale versions (web zoom 8–9 and 10–11): the full geometry is far too detailed there ------------------------
# rivers get a stronger simplification than roads: their meanders are wide (500–800 m) and would survive a light one
GEN = {"g1": dict(line_tol=500, river_tol=900, water_r=400, water_tol=150), "g2": dict(line_tol=280, river_tol=450, water_r=140, water_tol=60)}


# ---- networks that read continuous: strokes, components, loose ends ---------------------------------------------------
# A road or a river is mapped as many short OSM ways (split at every bridge, junction, name change). Drawn as they are,
# short pieces get dropped by the vector tiles at small zooms (holes in a motorway), and filtering pieces by length
# punches gaps into long routes. These tools rebuild the network as a few long, continuous lines instead.
SNAP = 0.5


def _k(p):
    return (round(p[0] / SNAP), round(p[1] / SNAP))


def noded(lines):
    """split lines at every intersection, so the network becomes a graph of segments between nodes"""
    return [l for l in parts(unary_union(list(lines))) if l.geom_type == "LineString" and l.length > 0]


def _graph(segs):
    nodes = defaultdict(list)
    for i, s in enumerate(segs):
        nodes[_k(s.coords[0])].append((i, 0))
        nodes[_k(s.coords[-1])].append((i, 1))
    return nodes


def _dir(seg, end, look):
    """unit vector from the node into the segment, measured over `look` metres (or half the segment)"""
    t = min(seg.length * 0.5, look)
    p0 = seg.coords[0] if end == 0 else seg.coords[-1]
    p1 = seg.interpolate(t if end == 0 else seg.length - t).coords[0]
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    n = hypot(dx, dy) or 1.0
    return dx / n, dy / n


def strokes(segs, look=50.0, max_turn=60.0):
    """chain segments into long strokes: at every node the two branches that continue the straightest (turning by at
    most max_turn degrees) are joined — 'good continuation', so a road or river reads from where to where"""
    segs = [s for s in segs if s.length > 0]
    nodes = _graph(segs)
    limit = -cos(radians(max_turn))
    link = {}
    for inc in nodes.values():
        if len(inc) < 2: continue
        dirs = [(_dir(segs[i], e, look), (i, e)) for i, e in inc]
        pairs = []
        for a in range(len(dirs)):
            for b in range(a + 1, len(dirs)):
                (va, ea), (vb, eb) = dirs[a], dirs[b]
                if ea[0] == eb[0]: continue
                d = va[0] * vb[0] + va[1] * vb[1]   # -1 = straight on
                if d <= limit: pairs.append((d, ea, eb))
        pairs.sort()
        for d, ea, eb in pairs:
            if ea in link or eb in link: continue
            link[ea], link[eb] = eb, ea
    seen, out = set(), []
    for i in range(len(segs)):
        if i in seen: continue
        cur, e = i, 0                       # walk back to the start of the chain
        for _ in range(len(segs)):
            nxt = link.get((cur, e))
            if nxt is None or nxt[0] == i: break
            cur, e = nxt[0], 1 - nxt[1]
        coords, s = [], cur
        while s not in seen:                # then forward, joining segments end to end
            seen.add(s)
            c = list(segs[s].coords)
            if e == 1: c.reverse()
            coords.extend(c if not coords else c[1:])
            nxt = link.get((s, 1 - e))
            if nxt is None: break
            s, e = nxt
        if len(coords) >= 2: out.append(LineString(coords))
    return out


def components(segs, gap, connectors=()):
    """groups of segments connected to each other, bridging gaps up to `gap` metres; connector polygons (reservoirs a
    river runs into and out of) join what touches them"""
    geoms = list(segs) + list(connectors)
    if not geoms: return []
    parent = list(range(len(geoms)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    left, right = shapely.STRtree(geoms).query(geoms, predicate="dwithin", distance=gap)
    for a, b in zip(left, right):
        ra, rb = find(int(a)), find(int(b))
        if ra != rb: parent[ra] = rb
    groups = defaultdict(list)
    for i in range(len(segs)): groups[find(i)].append(segs[i])
    return list(groups.values())


def footprint_length(segs, gap):
    """length of the corridor a group of lines covers: a dual carriageway counts once, not twice"""
    return unary_union(segs).buffer(gap, quad_segs=2).area / (2 * gap)


def prune_spurs(segs, min_len, rounds=10):
    """drop the short loose ends of a network (side streams, stub roads), so the main stems read continuous"""
    segs = list(segs)
    for _ in range(rounds):
        nodes = _graph(segs)
        drop = set()
        for inc in nodes.values():
            if len(inc) != 1: continue
            (s, e), path, length = inc[0], [], 0.0
            while True:
                path.append(s); length += segs[s].length
                far = _k(segs[s].coords[-1] if e == 0 else segs[s].coords[0])
                if len(nodes[far]) != 2 or length >= min_len: break
                nxt = [x for x in nodes[far] if x[0] != s]
                if not nxt: break
                s, e = nxt[0]
            if length < min_len and len(nodes[far]) >= 3:
                drop.update(path)
        if not drop: break
        segs = [s for i, s in enumerate(segs) if i not in drop]
    return segs


def bridge_through(segs, connectors, gap, max_area=None):
    """lines that end at a reservoir are joined through it (to its centre): at small zooms where the reservoir itself
    is not drawn, the river runs on instead of stopping at the dam, and its short stretch below the dam is no longer a
    loose end to be pruned. Reservoirs big enough to be drawn at this zoom (max_area) need no bridge, and a bridge is
    only made where it stays on the water, never as a straight line across the land of a branching reservoir."""
    nodes = _graph(segs)
    ends = [segs[inc[0][0]].coords[0 if inc[0][1] == 0 else -1] for inc in nodes.values() if len(inc) == 1]
    if not ends or not connectors: return []
    pts = [Point(p) for p in ends]
    tree = shapely.STRtree(pts)
    bridges = []
    for poly in connectors:
        if max_area and poly.area > max_area: continue
        near = tree.query(poly, predicate="dwithin", distance=gap)
        if len(near) < 2: continue
        c, water = poly.representative_point().coords[0], poly.buffer(gap)
        inside = [LineString([ends[i], c]) for i in near]
        inside = [b for b in inside if b.within(water)]
        if len(inside) >= 2: bridges += inside
    return bridges


def gen_network(lines, *, tol, gap, min_comp, min_spur=0, connectors=(), max_turn=60, bridge_max_area=None):
    """a continuous small-scale version of a network: whole connected networks shorter than min_comp are left out
    (isolated fragments), short loose ends are pruned, the rest is chained into long strokes, simplified, rounded"""
    segs = noded(lines)
    kept = []
    for comp in components(segs, gap, connectors):
        if footprint_length(comp, gap) >= min_comp:
            kept += comp
    kept += bridge_through(kept, connectors, gap, bridge_max_area)
    if min_spur: kept = prune_spurs(kept, min_spur)
    out = []
    for st in strokes(kept, look=tol, max_turn=max_turn):
        if st.length < tol: continue
        s = st.simplify(tol)
        out.append(LineString(chaikin(list(s.coords), 2, closed=False)).simplify(tol * 0.08))
    return out


def merge_by_attrs(items, look=20.0, max_turn=45):
    """join smoothed pieces that share all attributes back into long lines (through junctions where they continue
    straight): tiny pieces would otherwise be dropped by the vector tiles, leaving holes in roads and rivers"""
    groups = defaultdict(list)
    for g, a in items: groups[tuple(a.items())].append(g)
    return [(st, dict(k)) for k, gs in groups.items() for st in strokes(gs, look=look, max_turn=max_turn)]


def gen_water(polys, r, tol):
    """lakes and reservoirs for small scales: an opening (shrink, then grow) removes arms narrower than 2r, then the
    outline is simplified and rounded"""
    opened = unary_union(polys).buffer(-r, quad_segs=4).buffer(r, quad_segs=4)
    out = []
    for p in parts(opened):
        if p.geom_type != "Polygon" or p.area < (3 * r) ** 2: continue
        s = p.simplify(tol, preserve_topology=True)
        for q in parts(s):
            if q.geom_type == "Polygon":
                out.append(Polygon(chaikin(list(q.exterior.coords), 2, True)).buffer(0))
    return [(g, {"label": ""}) for g in out if not g.is_empty]


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


def ink_pieces(items, tol, min_wedge=4):
    """the coast's ink technique applied to arbitrary water polygons: each shape unioned with a coarser smoothed
    copy of itself (the "hand", wandering slightly off the true edge) -> (wedges where the hand strays outside,
    the ink outline as a line). Gives lakes/reservoirs the same artistic edge as the coastline, not a plain outline."""
    wedges, inks = [], []
    for g, a in items:
        loose = soft(g, tol, iterations=2, thin=0.3)
        inked = unary_union([g, loose])
        for p in parts(inked.difference(g)):
            if p.geom_type == "Polygon" and p.area > min_wedge:
                wedges.append((p, a))
        inks.append((inked.boundary, a))
    return wedges, inks


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
    save("roads", merge_by_attrs(smooth_lines(items)), "line")
    # small scales: per class, a continuous network (main carriageways only, no ramps), isolated fragments left out
    SMALL = {   # name: {class: (min_zoom included up to, gap bridged, min network length, min loose end)}
        "g1": {"motorway": (8, 300, 40_000, 5_000), "primary": (9, 150, 12_000, 2_000)},
        "g2": {"motorway": (8, 150, 15_000, 2_000), "primary": (9, 80, 5_000, 800),
               "secondary": (10, 60, 4_000, 600), "tertiary": (11, 50, 3_000, 500)},
    }
    # a main route (IP 8 Sines–Beja, IC 4…) is mapped partly as trunk and partly as primary: at small scales the
    # whole route is drawn as one, so it reads continuous instead of as dashes (European E-refs are too broad for this)
    tokens = lambda a: {r.strip() for r in a.get("ref", "").split(";") if r.strip() and not r.strip().startswith("E")}
    main_refs = set().union(*(tokens(a) for _, a in items if a["cls"] == "motorway" and a["min_zoom"] == 8))
    same_route = lambda a: a["cls"] == "primary" and tokens(a) & main_refs
    for name, classes in SMALL.items():
        out = []
        for cls, (maxz, gap, min_comp, min_spur) in classes.items():
            lines = [g for g, a in items if (a["cls"] == cls and a["min_zoom"] <= maxz) or (cls == "motorway" and same_route(a))]
            out += [(g, {"cls": cls}) for g in gen_network(lines, tol=GEN[name]["line_tol"], gap=gap, min_comp=min_comp, min_spur=min_spur)]
        save(f"roads_{name}", out, "line")
    rails = [(p, {"label": ""}) for el in load("railways") for l in [way_line(el)] if l for p in parts(merc(l).intersection(DETAIL)) if p.geom_type == "LineString"]
    save("railways", merge_by_attrs(smooth_lines(rails, tol=5.0)), "line")


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


def areas(src, attrs_of, min_area, frame=DETAIL, clip=None):
    """clip: an extra geometry (e.g. the land polygon) each feature is also intersected with, so a feature that
    OSM maps slightly past the coast (common for protected-area polygons) never paints over the sea"""
    items = []
    for el in load(src):
        g = area_geom(el)
        if g is None or g.is_empty: continue
        g = merc(g).intersection(frame)
        if clip is not None:
            g = g.intersection(clip)
            if g.is_empty: continue
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


def water_and_land_cover(land):
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
    # clipped to the land polygon: a nature reserve / wood polygon that OSM maps slightly past the coast must not paint over the sea
    save("greens", areas("greens", green_attrs, 2000, clip=land), "polygon")

    # rivers and streams: cut where they run through a lake or reservoir (the water body is drawn instead), smoothed;
    # rivers appear by their total length, streams only close in, very short ones not at all
    water_g = {}
    for name, maxz in (("g1", 9), ("g2", 11)):
        water_g[name] = gen_water([g for g, a in water if a["min_zoom"] <= maxz], GEN[name]["water_r"], GEN[name]["water_tol"])
        save(f"water_{name}", water_g[name], "polygon")
    # the coast's hand-inked edge, also for lakes/reservoirs: wobble scaled like the land bands (g1 ~ b1, g2 ~ b2,
    # full detail ~ b3), so a lake's edge wanders the same artistic amount as the coastline does at that same zoom
    WATER_INK_TOL = {"g1": 320, "g2": 90, "full": 14}
    for name in ("g1", "g2"):
        wd, ik = ink_pieces(water_g[name], WATER_INK_TOL[name])
        save(f"water_{name}_wedges", wd, "polygon")
        save(f"water_{name}_ink", ik, "line")
    wd, ik = ink_pieces(water, WATER_INK_TOL["full"])
    save("water_wedges", wd, "polygon")
    save("water_ink", ik, "line")
    # rivers are NOT cut at lakes/reservoirs: a lake's own min_zoom can be higher than the river's, so cutting the
    # river unconditionally left a permanent gap wherever a not-yet-visible pond happened to sit (a real bug seen in
    # practice). Water bodies are drawn above rivers in algarve_pro.py, so once a lake becomes visible it simply
    # covers the river underneath it — no cutting needed, and no risk of a gap with nothing to fill it.
    lines = []
    for el in load("waterways"):
        t = el.get("tags", {}); l = way_line(el)
        if l is None: continue
        ww = t.get("waterway")
        for p in parts(merc(l).intersection(DETAIL)):
            if p.geom_type == "LineString" and p.length > 30:
                lines.append((p, {"cls": "river" if ww == "river" else "stream", "label": t.get("name") or "", "min_zoom": 0}))
    raw_rivers = [(g, a) for g, a in lines if a["cls"] == "river"]   # for the small-scale (generalized) versions
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
    save("waterways", merge_by_attrs(smooth_lines(lines)), "line")
    # small scales: whole river systems (names ignored: a river often changes name along its course), joined through
    # the reservoirs they run into, short side streams pruned, so only continuous main stems remain
    lakes = [g for g, a in water if a["kind"] == "lake" and g.area > 5e5]
    # bridge_max_area: reservoirs drawn at that zoom (WATER_ZOOM: zoom 8 from 15 km², zoom 10 from 2 km²) cover the gap
    for name, gap, min_comp, min_spur, drawn in (("g1", 200, 60_000, 25_000, 1.5e7), ("g2", 100, 20_000, 8_000, 2e6)):
        rivers = gen_network([g for g, _ in raw_rivers], tol=GEN[name]["river_tol"], gap=gap, min_comp=min_comp,
                             min_spur=min_spur, connectors=lakes, max_turn=70, bridge_max_area=drawn)
        save(f"waterways_{name}", [(g, {"cls": "river", "label": ""}) for g in rivers], "line")


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
