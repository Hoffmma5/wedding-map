import json, math, random
from pathlib import Path
from shapely.geometry import Polygon, MultiPolygon, Point, LineString
from shapely.ops import unary_union
from pyproj import Transformer
VLON, VLAT = -8.45, 37.12
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
countries = []; polys_all = []
for g in t['objects']['countries']['geometries']:
    name = g['properties']['name']
    if name == 'Antarctica': continue
    parts = [g['arcs']] if g['type'] == 'Polygon' else g.get('arcs', []) if g['type'] == 'MultiPolygon' else []
    rings_out = []; kept = []
    for poly in parts:
        rr = [unwrap(ring(r)) for r in poly]
        if any(angdist(*p) > 158 for p in rr[0]): continue
        shp = Polygon(rr[0], rr[1:]).buffer(0)
        if shp.is_empty: continue
        near = max(angdist(*p) for p in rr[0]) < 45
        if shp.area < (0.0006 if near else 0.08): continue
        polys_all.append(shp)
        kept.append(shp)
    for shp in kept:
        for part in (shp.geoms if isinstance(shp, MultiPolygon) else [shp]):
            near = max(angdist(*p) for p in part.exterior.coords) < 45
            s = part.simplify(0.02 if near else 0.12, preserve_topology=True)
            for geom in (s.geoms if isinstance(s, MultiPolygon) else [s]):
                for rg in [geom.exterior] + list(geom.interiors):
                    c = [round(v, 2) for xy in rg.coords for v in xy]
                    if len(c) >= 8: rings_out.append(c)
    if rings_out: countries.append({'n': name, 'r': rings_out})
# dissolved coastline (no internal borders) for the coastal water lines: half the edges, nothing hidden under land
coast = []
cu = unary_union([p.buffer(0.01) for p in polys_all]).buffer(-0.01)
for part in (cu.geoms if isinstance(cu, MultiPolygon) else [cu]):
    if part.area < 0.004: continue
    near = max(angdist(*p) for p in part.exterior.coords) < 45
    s = part.simplify(0.03 if near else 0.12, preserve_topology=True)
    for geom in (s.geoms if isinstance(s, MultiPolygon) else [s]):
        for rg in [geom.exterior] + [i for i in geom.interiors if Polygon(i).area > 0.05]:
            c = [round(v, 2) for xy in rg.coords for v in xy]
            if len(c) >= 8: coast.append(c)
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
# graticule every 15°, split beyond 150° from venue
grat = []
def add_line(pts):
    seg = []
    for p in pts:
        if angdist(*p) <= 150: seg.append([round(p[0], 2), round(p[1], 2)])
        else:
            if len(seg) > 1: grat.append(seg)
            seg = []
    if len(seg) > 1: grat.append(seg)
for lon in range(-180, 180, 15): add_line([(lon, lat) for lat in range(-80, 81, 2)])
for lat in range(-75, 76, 15): add_line([(lon, lat) for lon in range(-180, 181, 2)])
json.dump({'countries': countries, 'coast': coast, 'waves': waves, 'grat': grat}, open(OUT, 'w'), separators=(',', ':'))
print(len(countries), 'countries', len(coast), 'coast rings', len(waves), 'waves', len(grat), 'grat lines', OUT.stat().st_size//1024, 'KB')
