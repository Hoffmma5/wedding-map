"""Download OpenStreetMap data for the "Azulejo Algarve" large-scale basemap via the Overpass API.

Data © OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright).
Results are cached in data-raw/osm/*.json, so each query runs only once; delete a file to fetch it again.

  DETAIL   the Algarve (plus the Spanish side of the Guadiana): everything from motorways to residential streets
  CONTEXT  south Portugal, Andalusia and north Morocco: coastline, main roads and towns for the 1:2M views
"""
import json
import time
import urllib.parse
import urllib.request

from generalize import ROOT

OUT = ROOT / "data-raw/osm"
OUT.mkdir(parents=True, exist_ok=True)
DETAIL = (36.90, -9.05, 37.65, -7.25)     # south, west, north, east
CONTEXT = (35.00, -11.50, 40.00, -4.50)
# public Overpass instances, tried in turn (the main one is often overloaded)
APIS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter"]

QUERIES = {
    "coastline": (CONTEXT, 'way["natural"="coastline"]({bbox});'),
    "context_roads": (CONTEXT, 'way["highway"~"^(motorway|trunk)$"]({bbox});'),
    "context_places": (CONTEXT, 'node["place"~"^(city|town)$"]({bbox});'),
    "roads": (DETAIL, 'way["highway"~"^(motorway|trunk|primary|secondary|tertiary|motorway_link|trunk_link|primary_link|'
                      'secondary_link|tertiary_link|unclassified|residential|living_street|pedestrian)$"]({bbox});'),
    "railways": (DETAIL, 'way["railway"="rail"]({bbox});'),
    "places": (DETAIL, 'node["place"~"^(city|town|village|hamlet|suburb|neighbourhood|locality|island)$"]({bbox});'),
    "waterways": (DETAIL, 'way["waterway"~"^(river|stream|canal)$"]({bbox});'),
    "water": (DETAIL, '(way["natural"="water"]({bbox}); relation["natural"="water"]({bbox}); '
                      'way["landuse"="reservoir"]({bbox}); relation["landuse"="reservoir"]({bbox}););'),
    "beaches": (DETAIL, '(way["natural"="beach"]({bbox}); relation["natural"="beach"]({bbox}););'),
    "wetlands": (DETAIL, '(way["natural"="wetland"]({bbox}); relation["natural"="wetland"]({bbox}););'),
    "greens": (DETAIL, '(way["leisure"~"^(golf_course|park|nature_reserve)$"]({bbox}); relation["leisure"~"^(golf_course|park)$"]({bbox}); '
                       'way["landuse"~"^(forest)$"]({bbox}); relation["landuse"="forest"]({bbox}); '
                       'way["natural"="wood"]({bbox}); relation["natural"="wood"]({bbox}););'),
    "peaks": (DETAIL, 'node["natural"="peak"]["name"]({bbox});'),
}


TILE = 1.5   # degrees: big queries are asked tile by tile (the public servers time out on large ones)


def tiles(bbox):
    s, w, n, e = bbox
    out = []
    y = s
    while y < n:
        x = w
        while x < e:
            out.append((round(y, 4), round(x, 4), round(min(y + TILE, n), 4), round(min(x + TILE, e), 4)))
            x += TILE
        y += TILE
    return out


def query(label, bbox, body):
    q = f"[out:json][timeout:300];{body.format(bbox=','.join(map(str, bbox)))}out geom;"
    for attempt in range(10):
        api = APIS[attempt % len(APIS)]
        req = urllib.request.Request(api, data=urllib.parse.urlencode({"data": q}).encode(),
                                     headers={"User-Agent": "azulejo-basemap-build/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=400) as r:
                data = json.loads(r.read())   # complete JSON or an exception: never cache half a response
            if "remark" in data and "error" in data["remark"].lower():
                raise RuntimeError(data["remark"][:120])
            return data["elements"]
        except Exception as e:   # Overpass is busy now and then: wait and retry on the next instance
            print(f"  {label} attempt {attempt + 1} ({api.split('/')[2]}) failed: {e}", flush=True)
            time.sleep(10 + 10 * attempt)
    raise SystemExit(f"could not fetch {label}")


def fetch(name, bbox, body):
    path = OUT / f"{name}.json"
    if path.exists():
        print(f"{name:<15} cached ({path.stat().st_size / 1e6:.1f} MB)", flush=True)
        return
    parts = tiles(bbox)
    seen, elements = set(), []
    for i, t in enumerate(parts):
        tile_path = OUT / f"_{name}_{i}.json"   # per-tile cache: a failed run resumes where it stopped
        if tile_path.exists():
            els = json.loads(tile_path.read_text(encoding="utf-8"))
        else:
            els = query(f"{name} tile {i + 1}/{len(parts)}", t, body)
            tile_path.write_text(json.dumps(els), encoding="utf-8")
            time.sleep(2)   # be gentle with the public servers
        for el in els:   # a way crossing tile edges comes back in each tile: keep it once
            k = (el["type"], el["id"])
            if k not in seen:
                seen.add(k); elements.append(el)
    path.write_text(json.dumps({"elements": elements}), encoding="utf-8")
    for i in range(len(parts)): (OUT / f"_{name}_{i}.json").unlink(missing_ok=True)
    print(f"{name:<15} {len(elements):>7} elements  {path.stat().st_size / 1e6:.1f} MB  ({len(parts)} tiles)", flush=True)


if __name__ == "__main__":
    for name, (bbox, body) in QUERIES.items():
        fetch(name, bbox, body)
