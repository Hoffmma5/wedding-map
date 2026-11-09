import json, math, random
from pathlib import Path
from shapely.geometry import Polygon, MultiPolygon, Point, LineString
from shapely.ops import unary_union
from shapely.geometry.polygon import orient
from pyproj import Transformer
VLON, VLAT = -8.45, 37.12
MAX_DEG = 158   # keep land up to here (the plates are cropped at 122° / 155.4°, see src/projection.js)
def angdist(lon, lat):
    p0, p = math.radians(VLAT), math.radians(lat)
    return math.degrees(math.acos(max(-1, min(1, math.sin(p0)*math.sin(p) + math.cos(p0)*math.cos(p)*math.cos(math.radians(lon - VLON))))))
ROOT = Path(__file__).resolve().parents[1]
# input: Natural Earth 1:50m via the world-atlas npm package (devDependency)
t = json.load(open(ROOT / 'node_modules/world-atlas/countries-50m.json', encoding='utf-8'))
OUT = ROOT / 'public/data/world.json'
sc, tr = t['transform']['scale'], t['transform']['translate']
arcs = []
for a in t['arcs']:
    x = y = 0; pts = []
    for dx, dy in a:
        x += dx; y += dy; pts.append((x*sc[0]+tr[0], y*sc[1]+tr[1]))
    arcs.append(pts)
def ring(ids):
    out = []
    for i in ids:
        p = arcs[i] if i >= 0 else arcs[~i][::-1]
        out.extend(p if not out else p[1:])
    return out
def unwrap(pts):
    # Natural Earth rings that cross the antimeridian (Chukotka, Wrangel, Fiji…) run along ±180° with only two
    # vertices; on a venue-centred map that meridian is not an edge, so it would show as a straight seam.
    # Move the western half by +360° so the ring is continuous (the projection handles lon > 180°).
    if any(x >= 170 for x, _ in pts) and any(x <= -170 for x, _ in pts):
        return [(x + 360 if x < 0 else x, y) for x, y in pts]
    return pts
# ---- generalization on the topology ------------------------------------------------------------------------
# world-atlas is TopoJSON: every border is one shared arc. Simplifying and smoothing each *arc* once (instead of each
# country on its own) keeps neighbours identical, so no slivers of sea open up along land borders.
NEAR_TOL, FAR_TOL = 0.02, 0.12        # Douglas-Peucker tolerance (deg) within / beyond 45° of the venue

def chaikin(pts, iterations=2, closed=False):
    """Corner cutting: rounds hard vertices; open arcs keep their end points (the border junctions)."""
    for _ in range(iterations):
        if len(pts) < 3: return pts
        cut = []
        for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
            cut += [(0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1), (0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1)]
        pts = cut + [cut[0]] if closed else [pts[0]] + cut + [pts[-1]]
    return pts

def soften(pts, tol, closed, iterations):
    if len(pts) >= 3:
        s = LineString(pts).simplify(tol, preserve_topology=False)
        pts = list(s.coords) if len(s.coords) >= (4 if closed else 2) else pts
    pts = chaikin(pts, iterations, closed)
    s = LineString(pts).simplify(tol * 0.3, preserve_topology=False)    # drop the near-collinear points again
    return [(round(x, 3), round(y, 3)) for x, y in s.coords]

_arc_cache = {}
def soft_arc(i):
    if i not in _arc_cache:
        a = unwrap(arcs[i])   # an arc that jumps across ±180° would otherwise be smoothed into a line across the globe
        near = min(angdist(*p) for p in a) < 45
        # near the venue: two rounds of smoothing (you zoom in there); far away one is enough
        _arc_cache[i] = soften(a, NEAR_TOL if near else FAR_TOL, closed=len(a) > 3 and a[0] == a[-1], iterations=2 if near else 1)
    return _arc_cache[i]

def soft_ring(ids):
    out = []
    for i in ids:
        p = soft_arc(i) if i >= 0 else soft_arc(~i)[::-1]
        out.extend(p if not out else p[1:])
    return out

countries = []; polys_all = []; drawn = []; drawn_names = []
for g in t['objects']['countries']['geometries']:
    name = g['properties']['name']
    if name == 'Antarctica': continue
    parts = [g['arcs']] if g['type'] == 'Polygon' else g.get('arcs', []) if g['type'] == 'MultiPolygon' else []
    rings_out = []
    for poly in parts:
        raw = [unwrap(ring(r)) for r in poly]
        if any(angdist(*p) > MAX_DEG for p in raw[0]): continue
        shp = Polygon(raw[0], raw[1:]).buffer(0)
        if shp.is_empty: continue
        near = max(angdist(*p) for p in raw[0]) < 45
        if shp.area < (0.0006 if near else 0.08): continue
        polys_all.append(shp)
        rr = [unwrap(soft_ring(r)) for r in poly]
        rr = [r for r in rr if len(r) >= 4]
        if not rr or Polygon(rr[0]).area < 1e-6: continue
        for c in rr: rings_out.append([v for xy in c for v in xy])
        drawn.append(Polygon(rr[0], rr[1:]).buffer(0)); drawn_names.append(name)
    if rings_out: countries.append({'n': name, 'r': rings_out})

# ---- the inked coast -----------------------------------------------------------------------------------------
# Dissolve the drawn countries (they share their borders exactly, so this is clean), then draw the ink from a
# coarser, smoothed copy (the UK look: land 0.02°, ink 0.03°) so it wanders like hand-inking. The ink shape is the
# union of land and that copy: where the hand strays out to sea the gap is filled with ink (the app fills it),
# where it strays inland the ink simply follows the land edge. No gaps between ink and land.
INK_TOL = 0.03
coast = []   # polygons: [exterior, hole, hole…] as flat lon/lat rings, exterior clockwise (Esri convention)
cu = unary_union(drawn).buffer(0)
def flat(rg): return [round(v, 3) for xy in rg.coords for v in xy]
def poly_rings(g):
    res = []
    for geom in (g.geoms if isinstance(g, MultiPolygon) else [g]):
        if geom.is_empty or geom.geom_type != "Polygon": continue
        geom = orient(geom, sign=-1.0)
        rings = [flat(geom.exterior)] + [flat(i) for i in geom.interiors if len(i.coords) >= 4]
        if len(rings[0]) >= 8: res.append(rings)
    return res
def wedge_rings(inked, land):
    """only the ink outside the land (what the eye sees as a thicker stroke): drawing just these, instead of a
    land-sized filled polygon under the land, means nothing big can flash while the map redraws tiles"""
    w = inked.difference(land)
    return poly_rings(unary_union([p for p in getattr(w, 'geoms', [w]) if p.geom_type == "Polygon" and p.area > 2e-6])) if not w.is_empty else []
wedges = []
ripple = []   # the water lines follow the inked coast, but need far fewer vertices (they are soft, wide strokes)
RIPPLE_TOL = 0.012
for part in (cu.geoms if isinstance(cu, MultiPolygon) else [cu]):
    if part.area < 0.0004: continue
    loose = part.simplify(INK_TOL, preserve_topology=True)
    if loose.geom_type == "Polygon" and not loose.is_empty:
        loose = Polygon(chaikin(list(loose.exterior.coords), 2, True), [chaikin(list(i.coords), 2, True) for i in loose.interiors]).buffer(0)
        loose = loose.simplify(0.006, preserve_topology=True)   # thin out the smoothed copy (the land keeps its vertices)
        land_part = part
        part = unary_union([part, loose])
        wedges += wedge_rings(part, land_part)
    ripple += poly_rings(part.simplify(RIPPLE_TOL, preserve_topology=True))
    for geom in (part.geoms if isinstance(part, MultiPolygon) else [part]):
        geom = orient(geom, sign=-1.0)       # clockwise exterior, counter-clockwise holes: holes stay unfilled
        rings = [flat(geom.exterior)] + [flat(i) for i in geom.interiors if len(i.coords) >= 4]
        if len(rings[0]) >= 8: coast.append(rings)

# ---- small-scale version (whole-world view) -----------------------------------------------------------------
# At world scale the detailed outlines look busy (fjords, specks of islands). Line simplification cannot remove a
# fjord (it is deep, so it survives), so this is done cartographically on the dissolved land instead:
# close it (grow, then shrink) to fill fjords and narrow inlets, drop small islands, simplify and smooth.
# Country borders become separate lines (only the shared arcs), clipped to that land; Portugal is cut from it too,
# so its coast matches the ink exactly. The app switches to this set when zoomed out beyond ~1:40M.
LO_CLOSE, LO_TOL, LO_MIN_AREA, LO_INK_TOL, LO_THIN = 0.06, 0.1, 0.3, 0.16, 0.03
land_hi = unary_union(drawn).buffer(0)
land_lo = land_hi.buffer(LO_CLOSE, quad_segs=4).buffer(-LO_CLOSE, quad_segs=4)
def lo_parts(g):
    out = []
    for part in (g.geoms if isinstance(g, MultiPolygon) else [g]):
        if part.area < LO_MIN_AREA: continue
        s = part.simplify(LO_TOL, preserve_topology=True)
        if s.is_empty or s.geom_type != "Polygon": continue
        s = Polygon(chaikin(list(s.exterior.coords), 2, True),
                    [chaikin(list(i.coords), 2, True) for i in s.interiors if Polygon(i).area > LO_MIN_AREA]).buffer(0)
        s = s.simplify(LO_THIN, preserve_topology=True)   # keep the curve, drop the surplus vertices
        out.extend(s.geoms if isinstance(s, MultiPolygon) else [s])
    return out
lo_land = unary_union(lo_parts(land_lo))
# ink: the lo land plus a looser, smoothed copy of it (same idea as the detailed coast)
lo_coast = []; lo_wedges = []
for part in (lo_land.geoms if isinstance(lo_land, MultiPolygon) else [lo_land]):
    loose = part.simplify(LO_INK_TOL, preserve_topology=True)
    if loose.geom_type == "Polygon" and not loose.is_empty:
        loose = Polygon(chaikin(list(loose.exterior.coords), 2, True), [chaikin(list(i.coords), 2, True) for i in loose.interiors]).buffer(0)
        loose = loose.simplify(LO_THIN, preserve_topology=True)
        land_part = part
        part = unary_union([part, loose])
        lo_wedges += wedge_rings(part, land_part)
    lo_coast += poly_rings(part)
# borders: arcs used by two countries, simplified + smoothed once, clipped to the lo land
use = {}
for g in t['objects']['countries']['geometries']:
    if g['properties']['name'] == 'Antarctica': continue
    polys = [g['arcs']] if g['type'] == 'Polygon' else g.get('arcs', []) if g['type'] == 'MultiPolygon' else []
    for poly in polys:
        for r in poly:
            for i in r: use[i if i >= 0 else ~i] = use.get(i if i >= 0 else ~i, 0) + 1
lo_borders = []
for i, n in use.items():
    if n < 2: continue
    a = unwrap(arcs[i])
    if max(angdist(*q) for q in a) > MAX_DEG: continue
    s = soften(a, LO_TOL, closed=False, iterations=2)
    if len(s) < 2: continue
    clipped = LineString(s).intersection(lo_land)
    for seg in getattr(clipped, 'geoms', [clipped]):
        if seg.geom_type == "LineString" and seg.length > 0.05:
            lo_borders.append([round(v, 3) for xy in seg.coords for v in xy])
pt_hi = unary_union([d for d, c in zip(drawn, drawn_names) if c == "Portugal"])
lo_portugal = poly_rings(lo_land.intersection(pt_hi.buffer(0.02)))
lo = {'land': poly_rings(lo_land), 'coast': lo_coast, 'wedges': lo_wedges, 'borders': lo_borders, 'portugal': lo_portugal}
land = unary_union(polys_all).buffer(0.9)
# waves on an even grid in venue-centred LAEA
fwd = Transformer.from_crs('EPSG:4326', f'+proj=laea +lat_0={VLAT} +lon_0={VLON} +datum=WGS84 +units=m', always_xy=True)
inv = Transformer.from_crs(f'+proj=laea +lat_0={VLAT} +lon_0={VLON} +datum=WGS84 +units=m', 'EPSG:4326', always_xy=True)
random.seed(3); waves = []
R = 12_300_000
for step, r0, r1 in [(260_000, 0, 4_200_000), (520_000, 4_200_000, R)]:
    n = int(R / step)
    for i in range(-n, n+1):
        for j in range(-n, n+1):
            x = i*step + (random.random()-.5)*step*.8; y = j*step + (random.random()-.5)*step*.8
            d = math.hypot(x, y)
            if not (r0 <= d < r1): continue
            lon, lat = inv.transform(x, y)
            if not (math.isfinite(lon) and math.isfinite(lat)) or angdist(lon, lat) > 150: continue
            if land.contains(Point(lon, lat)): continue
            waves.append([round(lon, 3), round(lat, 3)])
# graticule every 15°, split beyond 158° from venue
grat = []
def add_line(pts):
    seg = []
    for p in pts:
        if angdist(*p) <= 158: seg.append([round(p[0], 2), round(p[1], 2)])
        else:
            if len(seg) > 1: grat.append(seg)
            seg = []
    if len(seg) > 1: grat.append(seg)
for lon in range(-180, 180, 15): add_line([(lon, lat) for lat in range(-80, 81, 2)])
for lat in range(-75, 76, 15): add_line([(lon, lat) for lon in range(-180, 181, 2)])
json.dump({'countries': countries, 'coast': coast, 'ripple': ripple, 'wedges': wedges, 'lo': lo, 'waves': waves, 'grat': grat}, open(OUT, 'w'), separators=(',', ':'))
print(len(lo['land']), 'lo land polys', len(lo['borders']), 'lo borders', len(countries), 'countries', len(coast), 'coast rings', len(waves), 'waves', len(grat), 'grat lines', OUT.stat().st_size//1024, 'KB')
