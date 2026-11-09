import json, math, random
from pathlib import Path
from shapely.geometry import Polygon, MultiPolygon, Point, LineString
from shapely.ops import unary_union
from shapely.geometry.polygon import orient
from pyproj import Transformer
VLON, VLAT = -8.45, 37.12
MAX_DEG = 175   # keep land up to here (the plate is cropped at 166°, see src/projection.js); 180° is the antipode
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

countries = []; polys_all = []; drawn = []
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
        drawn.append(Polygon(rr[0], rr[1:]).buffer(0))
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
for part in (cu.geoms if isinstance(cu, MultiPolygon) else [cu]):
    if part.area < 0.0004: continue
    loose = part.simplify(INK_TOL, preserve_topology=True)
    if loose.geom_type == "Polygon" and not loose.is_empty:
        loose = Polygon(chaikin(list(loose.exterior.coords), 2, True), [chaikin(list(i.coords), 2, True) for i in loose.interiors]).buffer(0)
        loose = loose.simplify(0.006, preserve_topology=True)   # thin out the smoothed copy (the land keeps its vertices)
        part = unary_union([part, loose])
    for geom in (part.geoms if isinstance(part, MultiPolygon) else [part]):
        geom = orient(geom, sign=-1.0)       # clockwise exterior, counter-clockwise holes: holes stay unfilled
        rings = [flat(geom.exterior)] + [flat(i) for i in geom.interiors if len(i.coords) >= 4]
        if len(rings[0]) >= 8: coast.append(rings)
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
# graticule every 15°, split beyond 170° from venue
grat = []
def add_line(pts):
    seg = []
    for p in pts:
        if angdist(*p) <= 170: seg.append([round(p[0], 2), round(p[1], 2)])
        else:
            if len(seg) > 1: grat.append(seg)
            seg = []
    if len(seg) > 1: grat.append(seg)
for lon in range(-180, 180, 15): add_line([(lon, lat) for lat in range(-80, 81, 2)])
for lat in range(-75, 76, 15): add_line([(lon, lat) for lon in range(-180, 181, 2)])
json.dump({'countries': countries, 'coast': coast, 'waves': waves, 'grat': grat}, open(OUT, 'w'), separators=(',', ':'))
print(len(countries), 'countries', len(coast), 'coast rings', len(waves), 'waves', len(grat), 'grat lines', OUT.stat().st_size//1024, 'KB')
