"""Filter the Algarve layers out of a Geofabrik OpenStreetMap extract (faster and more reliable than Overpass).

    curl -L -o data-raw/pbf/portugal-latest.osm.pbf https://download.geofabrik.de/europe/portugal-latest.osm.pbf
    python scripts/algarve_pbf.py

Writes data-raw/osm/<layer>.json in the same shape as scripts/algarve_fetch.py (Overpass elements), so
scripts/algarve_data.py reads either. Areas (lakes, beaches, forests…, including multipolygons) are assembled by osmium
and stored as WKT. The Spanish bank of the Guadiana is not in the Portugal extract: that strip comes from one small
Overpass query at the end. Data © OpenStreetMap contributors, ODbL 1.0.
"""
import json

import osmium

from algarve_fetch import APIS, query   # the small Spanish strip
from generalize import ROOT

PBF = ROOT / "data-raw/pbf/portugal-latest.osm.pbf"
OUT = ROOT / "data-raw/osm"
S, W, N, E = 36.90, -9.05, 37.65, -7.25            # the detail frame (same as algarve_fetch.DETAIL)
SPAIN = (36.90, -7.46, 37.65, -7.25)               # east of the Guadiana

HIGHWAYS = {"motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link", "trunk_link", "primary_link",
            "secondary_link", "tertiary_link", "unclassified", "residential", "living_street", "pedestrian"}
PLACES = {"city", "town", "village", "hamlet", "suburb", "neighbourhood", "locality", "island"}


def inside(lon, lat):
    return W <= lon <= E and S <= lat <= N


def area_layer(t):
    if t.get("natural") == "water" or t.get("landuse") == "reservoir": return "water"
    if t.get("natural") == "beach": return "beaches"
    if t.get("natural") == "wetland": return "wetlands"
    if t.get("leisure") in ("golf_course", "park", "nature_reserve") or t.get("landuse") == "forest" or t.get("natural") == "wood":
        return "greens"
    return None


class Algarve(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.layers = {k: [] for k in ("roads", "railways", "places", "waterways", "water", "beaches", "wetlands", "greens", "peaks")}
        self.wkt = osmium.geom.WKTFactory()

    def node(self, n):
        t = n.tags
        if "place" not in t and t.get("natural") != "peak": return
        lon, lat = n.location.lon, n.location.lat
        if not inside(lon, lat): return
        el = {"type": "node", "id": n.id, "lat": lat, "lon": lon, "tags": dict(t)}
        if t.get("place") in PLACES: self.layers["places"].append(el)
        elif t.get("natural") == "peak" and "name" in t: self.layers["peaks"].append(el)

    def way(self, w):
        t = w.tags
        layer = ("roads" if t.get("highway") in HIGHWAYS else "railways" if t.get("railway") == "rail"
                 else "waterways" if t.get("waterway") in ("river", "stream", "canal") else None)
        if layer is None: return
        try:
            pts = [(nd.location.lon, nd.location.lat) for nd in w.nodes]
        except osmium.InvalidLocationError:
            return
        if not any(inside(x, y) for x, y in pts): return
        self.layers[layer].append({"type": "way", "id": w.id, "tags": dict(t), "geometry": [{"lon": x, "lat": y} for x, y in pts]})

    def area(self, a):
        layer = area_layer(a.tags)
        if layer is None: return
        try:
            ring = next(iter(a.outer_rings()))
            if not any(inside(nd.lon, nd.lat) for nd in ring): return
            wkt = self.wkt.create_multipolygon(a)
        except (StopIteration, RuntimeError, osmium.InvalidLocationError):
            return
        self.layers[layer].append({"type": "wkt", "id": a.id, "tags": dict(a.tags), "wkt": wkt})


SPANISH_STRIP = ('(way["highway"~"^(' + "|".join(sorted(HIGHWAYS)) + ')$"]({bbox}); way["railway"="rail"]({bbox}); '
                 'node["place"]({bbox}); way["waterway"~"^(river|stream|canal)$"]({bbox}); '
                 'way["natural"~"^(water|beach|wetland|wood)$"]({bbox}); way["landuse"~"^(reservoir|forest)$"]({bbox}); '
                 'way["leisure"~"^(golf_course|park|nature_reserve)$"]({bbox}););')


def add_spain(layers):
    """the Spanish bank of the Guadiana (Ayamonte, Isla Cristina): one small Overpass query"""
    try:
        els = query("Spanish strip", SPAIN, SPANISH_STRIP)
    except SystemExit as e:
        print(f"  skipped the Spanish strip ({e})")
        return
    for el in els:
        t = el.get("tags", {})
        if el["type"] == "node":
            if t.get("place") in PLACES and "name" in t: layers["places"].append(el)
            continue
        if t.get("highway") in HIGHWAYS: layers["roads"].append(el)
        elif t.get("railway") == "rail": layers["railways"].append(el)
        elif t.get("waterway") in ("river", "stream", "canal"): layers["waterways"].append(el)
        else:
            layer = area_layer(t)
            if layer: layers[layer].append(el)   # closed ways: assembled as polygons by algarve_data.area_geom
    print(f"  Spanish strip: {len(els)} elements")


if __name__ == "__main__":
    h = Algarve()
    h.apply_file(str(PBF), locations=True, idx="flex_mem")
    add_spain(h.layers)
    for name, els in h.layers.items():
        path = OUT / f"{name}.json"
        path.write_text(json.dumps({"elements": els}), encoding="utf-8")
        print(f"{name:<11} {len(els):>7} elements  {path.stat().st_size / 1e6:6.1f} MB")
