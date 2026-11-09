"""World-wide data for the "Azulejo" Web Mercator basemap (basemap/data/*.geojson).

Same generalization as the wedding map (scripts/generalize.py), but evenly detailed everywhere (no venue, no crop),
with Antarctica, every geometry split at the date line and clipped to Web Mercator's ±85.0511°.
Then run scripts/basemap_pro.py with ArcGIS Pro's Python to build the geodatabase, the Pro project and the .vtpk.
"""
import json

from shapely.affinity import translate
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, box, mapping
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from generalize import ROOT, Generalizer, inked_coast, load_topology, polygons_of, small_scale, unwrap

OUT = ROOT / 'basemap/data'
OUT.mkdir(parents=True, exist_ok=True)
LAT = 85.0511287798   # Web Mercator's limit

t, arcs = load_topology()
# Antarctica is already a valid lon/lat polygon (its ring closes along the -90° parallel), so it must not be unwrapped
antarctic_arcs = {i if i >= 0 else ~i for g in t['objects']['countries']['geometries'] if g['properties']['name'] == 'Antarctica'
                  for poly in polygons_of(g) for r in poly for i in r}
def close_pole(pts):
    """Close a ring that runs all the way round the globe along the -90° parallel (Web Mercator's clip at -85°
    then cuts that edge off anyway)."""
    xs = [x for x, _ in pts]
    if max(xs) - min(xs) < 350: return pts
    ring = pts[:-1] if pts[0] == pts[-1] else pts
    n = len(ring)
    i = max(range(n), key=lambda k: abs(ring[(k + 1) % n][0] - ring[k][0]))   # the step across the date line
    seq = ring[i + 1:] + ring[:i + 1]
    a, b = seq[0], seq[-1]
    return seq + [(b[0], -90.0), (a[0], -90.0), a]

def antarctic(rings):
    """world-atlas stores Antarctica for spherical rendering: the outer ring is a degenerate line along the South Pole
    and the coastline is a "hole". As a flat lon/lat polygon, the coastline closed along -90° is the outline."""
    if len(rings) > 1 and all(y < -89.9 for _, y in rings[0]):
        # everything south of 84°S is ice-covered land: fill it solid, so no sliver is left where coast and closure meet
        outline = Polygon(close_pole(rings[1])).buffer(0).union(box(-180, -90, 180, -84))
        outline = max(getattr(outline, 'geoms', [outline]), key=lambda p: p.area)
        return [list(outline.exterior.coords)] + rings[2:]
    return rings

gen = Generalizer(t, arcs, skip=(),
                  arc_params=lambda a: (0.02, 2),          # the detailed look everywhere
                  keep=lambda r: True,
                  min_area=lambda r: 0.0006,
                  unwrap_arc=lambda i, pts: pts if i in antarctic_arcs else unwrap(pts),
                  unwrap_ring=lambda name, pts: pts if name == 'Antarctica' else unwrap(pts),
                  fix_rings=lambda name, rings: antarctic(rings) if name == 'Antarctica' else rings)
countries, drawn, drawn_names, _ = gen.countries()
coast, wedges, ripple = inked_coast(drawn)
lo, _ = small_scale(gen, drawn, drawn_names)

# ---- back into -180…180 and the Mercator latitude range ------------------------------------------------------
WORLD = box(-180, -LAT, 180, LAT)
EAST = box(180, -LAT, 540, LAT)    # unwrapped parts (lon > 180) are shifted back by -360°

def to_shape(rings_list):
    polys = []
    for rings in rings_list:
        pts = [list(zip(r[0::2], r[1::2])) for r in rings]
        polys.append(Polygon(pts[0], pts[1:]).buffer(0))
    return unary_union(polys) if polys else Polygon()

def wrap(g):
    return unary_union([g.intersection(WORLD), translate(g.intersection(EAST), xoff=-360)])

def polygon_features(g, props=None):
    out = []
    for p in getattr(g, 'geoms', [g]):
        if p.geom_type == 'Polygon' and not p.is_empty and p.area > 1e-7:
            out.append({'type': 'Feature', 'properties': props or {}, 'geometry': mapping(orient(p, sign=1.0))})
    return out

def line_features(lines, props=None):
    out = []
    for flat_line in lines:
        g = wrap(LineString(list(zip(flat_line[0::2], flat_line[1::2]))))
        for seg in getattr(g, 'geoms', [g]):
            if seg.geom_type == 'LineString' and seg.length > 0:
                out.append({'type': 'Feature', 'properties': props or {}, 'geometry': mapping(seg)})
    return out

def save(name, features):
    path = OUT / f'{name}.geojson'
    path.write_text(json.dumps({'type': 'FeatureCollection', 'features': features}, separators=(',', ':')))
    print(f'{name:<14} {len(features):>6} features  {path.stat().st_size // 1024:>6} KB')

# countries: one feature per country, keep the name
feats = []
for c in countries:
    rings = c['r']
    # a country's flat rings mix exteriors and holes; rebuild them as polygons by containment
    polys = [Polygon(list(zip(r[0::2], r[1::2]))).buffer(0) for r in rings]
    polys.sort(key=lambda p: -p.area)
    shape = Polygon()
    for p in polys:
        shape = shape.difference(p) if shape.contains(p) else shape.union(p)
    feats += polygon_features(wrap(shape), {'name': c['n']})
save('countries', feats)
save('coast_ink', polygon_features(wrap(to_shape(coast))))
save('ink_wedges', polygon_features(wrap(to_shape(wedges))))
save('water_lines', polygon_features(wrap(to_shape(ripple))))
save('lo_land', polygon_features(wrap(to_shape(lo['land']))))
save('lo_ink', polygon_features(wrap(to_shape(lo['coast']))))
save('lo_wedges', polygon_features(wrap(to_shape(lo['wedges']))))
save('lo_borders', line_features(lo['borders']))
grat = []
for lon in range(-165, 180, 15): grat.append([v for lat in range(-85, 86, 1) for v in (lon, lat)])
for lat in range(-75, 76, 15): grat.append([v for lon in range(-180, 181, 2) for v in (lon, lat)])
save('graticule', line_features(grat))
save('ocean', [{'type': 'Feature', 'properties': {}, 'geometry': mapping(orient(WORLD, sign=1.0))}])
