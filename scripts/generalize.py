"""Shared cartographic generalization of Natural Earth 1:50m (world-atlas TopoJSON).

Used by scripts/world.py (the wedding map: data around the Algarve plate) and scripts/basemap_data.py (the world-wide
Web Mercator basemap). Everything works on lon/lat; the callers decide what to keep and how detailed each part is.

  countries      simplify + smooth every shared border arc once (neighbours stay identical, no slivers)
  inked_coast    the hand-inked coast: dissolved land ∪ a coarser smoothed copy, the wedges where that copy strays
                 out to sea, and a lighter outline for the coastal water lines
  small_scale    a calmer set for small scales: closed fjords, no specks of islands, borders as separate lines
"""
import json
from pathlib import Path

from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]


def load_topology():
    """Natural Earth 1:50m via the world-atlas npm package (devDependency): topology + decoded arcs (lon/lat)."""
    t = json.load(open(ROOT / 'node_modules/world-atlas/countries-50m.json', encoding='utf-8'))
    sc, tr = t['transform']['scale'], t['transform']['translate']
    arcs = []
    for a in t['arcs']:
        x = y = 0; pts = []
        for dx, dy in a:
            x += dx; y += dy; pts.append((x * sc[0] + tr[0], y * sc[1] + tr[1]))
        arcs.append(pts)
    return t, arcs


def polygons_of(g):
    return [g['arcs']] if g['type'] == 'Polygon' else g.get('arcs', []) if g['type'] == 'MultiPolygon' else []


def unwrap(pts):
    # Natural Earth rings that cross the antimeridian (Chukotka, Wrangel, Fiji…) run along ±180° with only two
    # vertices; on a venue-centred map that meridian is not an edge, so it would show as a straight seam.
    # Move the western half by +360° so the ring is continuous (the projection handles lon > 180°).
    if any(x >= 170 for x, _ in pts) and any(x <= -170 for x, _ in pts):
        return [(x + 360 if x < 0 else x, y) for x, y in pts]
    return pts


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


def flat(rg): return [round(v, 3) for xy in rg.coords for v in xy]


def poly_rings(g):
    """polygons as [exterior, holes…] flat lon/lat rings, exterior clockwise (Esri convention: holes stay holes)"""
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


class Generalizer:
    """
    arc_params(pts) -> (tolerance, smoothing iterations) for one border arc
    keep(raw_ring) -> bool, min_area(raw_ring) -> deg² for one polygon part
    unwrap_arc / unwrap_ring: how lon/lat is made continuous across ±180° (see unwrap)
    """

    def __init__(self, t, arcs, *, arc_params, keep, min_area, skip=('Antarctica',), unwrap_arc=None, unwrap_ring=None, fix_rings=None):
        self.t, self.arcs = t, arcs
        self.arc_params, self.keep, self.min_area, self.skip = arc_params, keep, min_area, set(skip)
        self.unwrap_arc = unwrap_arc or (lambda i, pts: unwrap(pts))
        self.unwrap_ring = unwrap_ring or (lambda name, pts: unwrap(pts))
        self.fix_rings = fix_rings or (lambda name, rings: rings)   # last say over a polygon's rings (Antarctica)
        self._cache = {}

    def ring(self, ids):
        out = []
        for i in ids:
            p = self.arcs[i] if i >= 0 else self.arcs[~i][::-1]
            out.extend(p if not out else p[1:])
        return out

    def soft_arc(self, i):
        if i not in self._cache:
            a = self.unwrap_arc(i, self.arcs[i])   # an arc that jumps across ±180° would otherwise be smoothed into a line across the globe
            tol, iterations = self.arc_params(a)
            self._cache[i] = soften(a, tol, closed=len(a) > 3 and a[0] == a[-1], iterations=iterations)
        return self._cache[i]

    def soft_ring(self, ids):
        out = []
        for i in ids:
            p = self.soft_arc(i) if i >= 0 else self.soft_arc(~i)[::-1]
            out.extend(p if not out else p[1:])
        return out

    def countries(self):
        """-> countries [{'n', 'r'}], drawn polygons, their names, raw polygons"""
        countries = []; polys_all = []; drawn = []; drawn_names = []
        for g in self.t['objects']['countries']['geometries']:
            name = g['properties']['name']
            if name in self.skip: continue
            rings_out = []
            for poly in polygons_of(g):
                raw = self.fix_rings(name, [self.unwrap_ring(name, self.ring(r)) for r in poly])
                if not self.keep(raw[0]): continue
                shp = Polygon(raw[0], raw[1:]).buffer(0)
                if shp.is_empty: continue
                if shp.area < self.min_area(raw[0]): continue
                polys_all.append(shp)
                rr = self.fix_rings(name, [self.unwrap_ring(name, self.soft_ring(r)) for r in poly])
                rr = [r for r in rr if len(r) >= 4]
                if not rr or Polygon(rr[0]).area < 1e-6: continue
                for c in rr: rings_out.append([v for xy in c for v in xy])
                drawn.append(Polygon(rr[0], rr[1:]).buffer(0)); drawn_names.append(name)
            if rings_out: countries.append({'n': name, 'r': rings_out})
        return countries, drawn, drawn_names, polys_all

    def shared_arcs(self):
        """indices of arcs used by two countries (land borders)"""
        use = {}
        for g in self.t['objects']['countries']['geometries']:
            if g['properties']['name'] in self.skip: continue
            for poly in polygons_of(g):
                for r in poly:
                    for i in r: use[i if i >= 0 else ~i] = use.get(i if i >= 0 else ~i, 0) + 1
        return [i for i, n in use.items() if n >= 2]


def inked_coast(drawn, ink_tol=0.03, ripple_tol=0.012):
    """The hand-inked coast. Dissolve the drawn countries (they share their borders exactly, so this is clean), then
    draw the ink from a coarser, smoothed copy (the UK look: land 0.02°, ink 0.03°) so it wanders like hand-inking.
    The ink shape is the union of land and that copy: where the hand strays out to sea, that wedge is inked; where it
    strays inland the ink simply follows the land edge. -> coast (ink outline), wedges, ripple (water-line outline)"""
    coast, wedges, ripple = [], [], []
    cu = unary_union(drawn).buffer(0)
    for part in (cu.geoms if isinstance(cu, MultiPolygon) else [cu]):
        if part.area < 0.0004: continue
        loose = part.simplify(ink_tol, preserve_topology=True)
        if loose.geom_type == "Polygon" and not loose.is_empty:
            loose = Polygon(chaikin(list(loose.exterior.coords), 2, True), [chaikin(list(i.coords), 2, True) for i in loose.interiors]).buffer(0)
            loose = loose.simplify(0.006, preserve_topology=True)   # thin out the smoothed copy (the land keeps its vertices)
            land_part = part
            part = unary_union([part, loose])
            wedges += wedge_rings(part, land_part)
        ripple += poly_rings(part.simplify(ripple_tol, preserve_topology=True))
        coast += poly_rings(part)
    return coast, wedges, ripple


LO_CLOSE, LO_TOL, LO_MIN_AREA, LO_INK_TOL, LO_THIN = 0.06, 0.1, 0.3, 0.16, 0.03


def small_scale(gen, drawn, drawn_names, keep_border=lambda pts: True, highlight=None):
    """At world scale the detailed outlines look busy (fjords, specks of islands). Line simplification cannot remove a
    fjord (it is deep, so it survives), so this is done cartographically on the dissolved land instead: close it
    (grow, then shrink) to fill fjords and narrow inlets, drop small islands, simplify and smooth. Country borders
    become separate lines (only the shared arcs), clipped to that land; a highlighted country (Portugal on the wedding
    map) is cut from it too, so its coast matches the ink exactly. -> dict of flat-ring geometries + the shapely land"""
    land_lo = unary_union(drawn).buffer(0).buffer(LO_CLOSE, quad_segs=4).buffer(-LO_CLOSE, quad_segs=4)
    parts = []
    for part in (land_lo.geoms if isinstance(land_lo, MultiPolygon) else [land_lo]):
        if part.area < LO_MIN_AREA: continue
        s = part.simplify(LO_TOL, preserve_topology=True)
        if s.is_empty or s.geom_type != "Polygon": continue
        s = Polygon(chaikin(list(s.exterior.coords), 2, True),
                    [chaikin(list(i.coords), 2, True) for i in s.interiors if Polygon(i).area > LO_MIN_AREA]).buffer(0)
        s = s.simplify(LO_THIN, preserve_topology=True)   # keep the curve, drop the surplus vertices
        parts.extend(s.geoms if isinstance(s, MultiPolygon) else [s])
    lo_land = unary_union(parts)
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
    lo_borders = []
    for i in gen.shared_arcs():
        a = gen.unwrap_arc(i, gen.arcs[i])
        if not keep_border(a): continue
        s = soften(a, LO_TOL, closed=False, iterations=2)
        if len(s) < 2: continue
        clipped = LineString(s).intersection(lo_land)
        for seg in getattr(clipped, 'geoms', [clipped]):
            if seg.geom_type == "LineString" and seg.length > 0.05:
                lo_borders.append([round(v, 3) for xy in seg.coords for v in xy])
    lo = {'land': poly_rings(lo_land), 'coast': lo_coast, 'wedges': lo_wedges, 'borders': lo_borders}
    if highlight:
        hi = unary_union([d for d, c in zip(drawn, drawn_names) if c == highlight])
        lo[highlight.lower()] = poly_rings(lo_land.intersection(hi.buffer(0.02)))
    return lo, lo_land
