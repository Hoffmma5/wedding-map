"""World data for the wedding map (public/data/world.json): Natural Earth 1:50m generalized around the Algarve plate.
The generalization itself lives in scripts/generalize.py (shared with the Web Mercator basemap, scripts/basemap_data.py)."""
import json, math, random
from shapely.geometry import Point
from shapely.ops import unary_union
from pyproj import Transformer
from generalize import ROOT, load_topology, Generalizer, inked_coast, small_scale

VLON, VLAT = -8.45, 37.12
MAX_DEG = 158   # keep land up to here (the plates are cropped at 122° / 155.4°, see src/projection.js)
def angdist(lon, lat):
    p0, p = math.radians(VLAT), math.radians(lat)
    return math.degrees(math.acos(max(-1, min(1, math.sin(p0)*math.sin(p) + math.cos(p0)*math.cos(p)*math.cos(math.radians(lon - VLON))))))
OUT = ROOT / 'public/data/world.json'
t, arcs = load_topology()

# detail depends on the distance from the venue: fine within 45° (where you zoom in), coarser beyond
NEAR_TOL, FAR_TOL = 0.02, 0.12
def arc_params(a):
    near = min(angdist(*p) for p in a) < 45
    return (NEAR_TOL, 2) if near else (FAR_TOL, 1)   # near the venue two rounds of smoothing, far away one is enough
gen = Generalizer(t, arcs, arc_params=arc_params,
                  keep=lambda r: not any(angdist(*p) > MAX_DEG for p in r),
                  min_area=lambda r: 0.0006 if max(angdist(*p) for p in r) < 45 else 0.08)
countries, drawn, drawn_names, polys_all = gen.countries()
coast, wedges, ripple = inked_coast(drawn)
lo, _ = small_scale(gen, drawn, drawn_names, keep_border=lambda a: max(angdist(*q) for q in a) <= MAX_DEG, highlight="Portugal")
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
