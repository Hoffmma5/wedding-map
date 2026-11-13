"""Build the "Azulejo Algarve" large-scale basemap in ArcGIS Pro: web zoom 8 (1:2.3M) down to street level.

Run with ArcGIS Pro's Python after scripts/algarve_pbf.py (or algarve_fetch.py) and scripts/algarve_data.py:
    "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" scripts\\algarve_pro.py [--vtpk]

Adds the map "Azulejo Algarve" to basemap/Algarve.aprx (own project and geodatabase), exports previews at four scales
and with --vtpk the package basemap/Azulejo_Algarve.vtpk. Same palette and symbol helpers as scripts/basemap_pro.py.
Data © OpenStreetMap contributors (ODbL), Natural Earth; labels in Instrument Serif (installed for all users).
"""
import shutil
import sys
from pathlib import Path

import arcpy

import basemap_pro as bp
from basemap_pro import COBALT, CREAM, SEA, INK, INK_ALPHA, WEB_MERCATOR, cim, fill, stroke, symbol, style, labels, points, dashed, zoom_scale

bp.FONT = "Instrument Serif"
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "basemap/algarve"
OUT = ROOT / "basemap"
GDB = OUT / "Algarve.gdb"
APRX = OUT / "Algarve.aprx"
VTPK = OUT / "Azulejo_Algarve.vtpk"
arcpy.env.overwriteOutput = True

SAND, GOLF, PARK, WOOD, TIDAL = (243, 229, 199), (221, 229, 196), (228, 234, 210), (232, 236, 216), (214, 228, 222)
TERRA, WHITE, OLIVE = (199, 142, 106), (255, 255, 255), (127, 143, 95)   # TERRA: muted clay, less "traffic orange"


def zr(lyr, name, z_from=None, z_to=None, where=None):
    """name, definition query and zoom range (z_to inclusive) of a layer"""
    if where: lyr.definitionQuery = where
    d = lyr.getDefinition("V3")
    d.name = name
    d.minScale = zoom_scale(z_from) if z_from is not None else 0
    d.maxScale = zoom_scale(z_to + 1) if z_to is not None else 0
    lyr.setDefinition(d)
    return lyr


def build_gdb():
    if GDB.exists(): shutil.rmtree(GDB)
    arcpy.management.CreateFileGDB(str(OUT), GDB.name)
    for path in sorted(SRC.glob("*.json")):
        arcpy.conversion.JSONToFeatures(str(path), str(GDB / path.stem))
        print(f"  {path.stem:<14} {arcpy.management.GetCount(str(GDB / path.stem))[0]:>6} features")


def road(fill_rgb, fill_px, case_px, case_alpha):
    """a road: fill over a slightly wider cobalt casing (no casing at the smallest scales)"""
    return symbol("line", [stroke(fill_px, fill_rgb)] + ([stroke(case_px, COBALT, case_alpha)] if case_px else []))


def water_ribbon(width, edge=1.0, edge_alpha=INK_ALPHA):
    """a river drawn the same way as a lake (pale SEA body, cobalt ink edge) instead of a solid cobalt line, so the
    colour reads as the same water flowing from the river into the lake rather than two different features.
    edge_alpha defaults to the same high opacity as the coast/lake ink: at a low alpha, two overlapping edges at a
    confluence (two separate OSM ways meeting, not one dissolved line) compound into a visibly darker "knot";
    at high alpha the compounding is barely perceptible, the same fix that solved it for road casings."""
    return symbol("line", [stroke(width + edge * 2, COBALT, edge_alpha), stroke(width, SEA)])


def water_lines(rings):
    layers = []
    for k, d in enumerate(rings):
        layers += [stroke(2 * d - 0.8, SEA), stroke(2 * d + 0.8, COBALT, round(16 * (1 - k / 4)))]
    return symbol("line", layers)


def by_zoom(add, fc, name, sym, zooms, where=None):
    """one layer per zoom level a feature appears at (its min_zoom): small features only show once there is room"""
    out = []
    for z in zooms:
        q = f"min_zoom = {z}" + (f" AND ({where})" if where else "")
        out.append(zr(style(add(fc), sym(), "r"), f"{name} (z{z})", z, where=q))
    return out


def add_layers(m):
    """the Algarve layers (web zoom 8 and larger), stacked top → bottom in map m"""
    add = lambda fc: m.addDataFromPath(str(GDB / fc))
    lay = []   # top → bottom

    # ---- labels (same type and colours as the atlas, so towns read the same on both sides of the switch at zoom 8)
    place_classes = [("Cities", "kind = 'city'", 10.5, 8, 1), ("Towns", "kind = 'town'", 9.5, 9, 2),
                     ("Villages", "kind = 'village' OR kind = 'island'", 9.0, 11, 3), ("Suburbs & hamlets", "kind IN ('suburb', 'hamlet')", 8.5, 13, 4),
                     ("Neighbourhoods", "kind IN ('neighbourhood', 'locality')", 8.0, 15, 5)]
    for n, q, size, z, prio in place_classes:
        lay.append(zr(labels(points(add("places"), visible=False), [(n, None, size, INK, 100, False, CREAM, 0.0, prio)], on_top=True),
                      f"Place labels: {n.lower()}", z, where=q))
    lay.append(zr(labels(points(add("peaks"), visible=False), [("Peaks", None, 8.0, OLIVE, 100, True, CREAM, 0.0, 6)], on_top=True), "Peak labels", 12))
    lay.append(zr(labels(style(add("roads"), symbol("line", [stroke(0.5, COBALT, 0)]), "Street names"),
                         [("Streets", None, 8.0, INK, 85, False, WHITE, 0.0, 8)], kind="line"), "Street names", 15, where="label <> ''"))
    lay.append(zr(labels(style(add("roads"), symbol("line", [stroke(0.5, COBALT, 0)]), "Road names"),
                         [("Roads", None, 8.5, INK, 85, False, WHITE, 0.0, 7)], kind="line"), "Road names", 13,
                  where="label <> '' AND cls IN ('primary', 'secondary', 'tertiary')"))
    lay.append(zr(labels(style(add("waterways"), symbol("line", [stroke(0.5, COBALT, 0)]), "River names"),
                         [("Rivers", None, 8.5, COBALT, 90, True, CREAM, 0.0, 6)], kind="line"), "River names", 12,
                  where="label <> '' AND cls = 'river'"))

    # ---- roads (motorway on top) and railways --------------------------------------------------------------------
    widths = {   # class: [(z_from, z_to, fill px, casing px, casing alpha)] — back to full opacity: at reduced
        # alpha, non-dissolved OSM ways (dual carriageways, segments meeting at junctions) show as uneven double-
        # dark patches where they overlap, and other data shows through; full opacity paints solid, no seam.
        "motorway": [(8, 10, 1.5, 0, 0), (11, 13, 2.8, 4.2, 75), (14, 14, 5.5, 7.5, 80), (15, None, 9.0, 11.5, 85)],
        "primary": [(9, 10, 1.0, 1.9, 45), (11, 13, 2.0, 3.2, 50), (14, 14, 4.6, 6.2, 55), (15, None, 8.0, 10.2, 60)],
        "secondary": [(10, 11, 0.9, 1.7, 40), (12, 13, 1.7, 2.8, 45), (14, 14, 4.0, 5.4, 50), (15, None, 7.0, 9.0, 55)],
        "tertiary": [(11, 13, 1.2, 2.2, 35), (14, 14, 3.4, 4.7, 45), (15, None, 6.2, 8.0, 50)],
        "minor": [(13, 13, 0.9, 1.7, 25), (14, 14, 2.4, 3.5, 35), (15, None, 5.2, 6.8, 40)],
    }
    # the geometry comes from the small-scale versions at zoom 8–9 (roads_g1) and 10–11 (roads_g2), in full from 12
    sources = [("roads_g1", 8, 9), ("roads_g2", 10, 11), ("roads", 12, None)]
    for cls in ("motorway", "primary", "secondary", "tertiary", "minor"):
        fill_rgb = TERRA if cls == "motorway" else WHITE
        for z0, z1, fw, cw, ca in reversed(widths[cls]):
            for fc, s0, s1 in reversed(sources):
                a, b = max(z0, s0), min(z1 if z1 else 99, s1 if s1 else 99)
                if a > b: continue
                b = None if b == 99 else b
                where = f"cls = '{cls}'" + (f" AND min_zoom <= {b if b else 20}" if fc == "roads" else "")
                lay.append(zr(style(add(fc), road(fill_rgb, fw, cw, ca), "r"), f"Roads: {cls} (z{a}" + (f"-{b})" if b else "+)"), a, b, where=where))
    lay.append(zr(style(add("borders"), symbol("line", [dashed(stroke(0.6, COBALT, 60))]), "r"), "Country borders", 8, 12))   # as the atlas
    lay.append(zr(style(add("railways"), symbol("line", [dashed(stroke(0.8, CREAM), (3, 3)), stroke(1.8, INK, 70)]), "r"), "Railways", 10))

    # ---- water bodies above the rivers: a river ends at the shore of the lake it flows into ------------------------
    # same three-layer technique as the coast (fill, then the wedges where the hand strays outside, then the ink
    # outline on top), so a lake's edge wanders like a hand-drawn line instead of a plain smooth outline
    water_fill = lambda: symbol("polygon", [fill(SEA)])
    wedge_sym = lambda: symbol("polygon", [fill(COBALT, INK_ALPHA)])
    ink_sym = lambda w=1.0: symbol("line", [stroke(w, COBALT, INK_ALPHA)])
    lay.append(zr(style(add("water_g1"), water_fill(), "r"), "Lakes & reservoirs fill (z8-9)", 8, 9))
    lay.append(zr(style(add("water_g2"), water_fill(), "r"), "Lakes & reservoirs fill (z10-11)", 10, 11))
    lay.append(zr(style(add("water"), water_fill(), "r"), "Lakes & reservoirs fill (z12)", 12, where="min_zoom <= 12"))
    lay += by_zoom(add, "water", "Lakes & reservoirs fill", water_fill, (14, 15, 16))
    # the ink wedges + outline are appended AFTER the fills (same relative order land/coast uses), which puts them
    # visually on top of the fill once the stacking pass below runs
    lay.append(zr(style(add("water_g1_wedges"), wedge_sym(), "r"), "Lake ink wedges (z8-9)", 8, 9))
    lay.append(zr(style(add("water_g1_ink"), ink_sym(1.4), "r"), "Lake ink (z8-9)", 8, 9))
    lay.append(zr(style(add("water_g2_wedges"), wedge_sym(), "r"), "Lake ink wedges (z10-11)", 10, 11))
    lay.append(zr(style(add("water_g2_ink"), ink_sym(1.2), "r"), "Lake ink (z10-11)", 10, 11))
    lay.append(zr(style(add("water_wedges"), wedge_sym(), "r"), "Lake ink wedges (z12)", 12, where="min_zoom <= 12"))
    lay.append(zr(style(add("water_ink"), ink_sym(1.0), "r"), "Lake ink (z12)", 12, where="min_zoom <= 12"))
    lay += by_zoom(add, "water_wedges", "Lake ink wedges", wedge_sym, (14, 15, 16))
    lay += by_zoom(add, "water_ink", "Lake ink", lambda: ink_sym(0.9), (14, 15, 16))
    # much lighter at small scale, where a river is background context, not the subject — at z8-9 the old
    # width+alpha made rivers visually louder than roads, towns or anything else and dominated the map
    lay.append(zr(style(add("waterways_g1"), water_ribbon(0.45, edge=0.35, edge_alpha=55), "r"), "Rivers (z8-9)", 8, 9))
    lay.append(zr(style(add("waterways_g2"), water_ribbon(0.6, edge=0.4, edge_alpha=60), "r"), "Rivers (z10-11)", 10, 11))
    lay.append(zr(style(add("waterways"), water_ribbon(0.55, edge=0.4, edge_alpha=62), "r"), "Rivers (z12+)", 12, where="cls = 'river' AND min_zoom <= 12"))
    lay += by_zoom(add, "waterways", "Streams", lambda: water_ribbon(0.6, edge=0.5, edge_alpha=60), (15, 16), where="cls = 'stream'")

    # ---- land cover on the land ------------------------------------------------------------------------------------
    lay += by_zoom(add, "wetlands", "Tidal flats & marsh", lambda: symbol("polygon", [fill(TIDAL)]), (10, 12, 14, 15))
    lay += by_zoom(add, "beaches", "Beaches", lambda: symbol("polygon", [stroke(0.6, (214, 180, 120)), fill(SAND)]), (11, 13, 14))
    lay.append(zr(style(add("greens"), symbol("polygon", [fill(GOLF)]), "r"), "Golf courses", 11, where="cls = 'golf'"))
    lay += by_zoom(add, "greens", "Parks", lambda: symbol("polygon", [fill(PARK)]), (12, 14, 15), where="cls = 'park'")
    lay += by_zoom(add, "greens", "Woods", lambda: symbol("polygon", [fill(WOOD)]), (11, 13, 14, 15), where="cls = 'wood'")

    # ---- the land and its inked coast, in three bands --------------------------------------------------------------
    bands = [("b3", 14, None, None), ("b2", 11, 13, "inner"), ("b2", 11, None, "outer"), ("b1", 8, 10, "inner"), ("b1", 8, None, "outer")]
    q = lambda part: f"part = '{part}'" if part else None
    for b, z0, z1, part in bands:
        lay.append(zr(style(add(f"{b}_land"), symbol("polygon", [fill(CREAM)]), "r"), f"Land {b} {part or ''}".strip(), z0, z1, where=q(part)))
    for b, z0, z1, part in bands:
        lay.append(zr(style(add(f"{b}_wedges"), symbol("polygon", [fill(COBALT, INK_ALPHA)]), "r"), f"Ink wedges {b} {part or ''}".strip(), z0, z1, where=q(part)))
        lay.append(zr(style(add(f"{b}_ink"), symbol("line", [stroke(1.8, COBALT, INK_ALPHA)]), "r"), f"Coast ink {b} {part or ''}".strip(), z0, z1, where=q(part)))
    for b, z0, z1, part in bands:   # three rings at every band: the atlas also has three from zoom 6
        lay.append(zr(style(add(f"{b}_ripple"), water_lines([3, 7.5, 12]), "r"), f"Water lines {b} {part or ''}".strip(), z0, z1, where=q(part)))
    lay.append(zr(style(add("sea"), symbol("polygon", [fill(SEA)]), "r"), "Sea", 8))

    for upper, lower in zip(lay, lay[1:]):
        m.moveLayer(upper, lower, "AFTER")
    return lay


def build_map(aprx):
    m = aprx.createMap("Azulejo Algarve", "MAP")
    for lyr in m.listLayers(): m.removeLayer(lyr)
    m.spatialReference = WEB_MERCATOR
    add_layers(m)
    d = m.getDefinition("V3")   # vector tiles are labelled with the Standard label engine
    d.generalPlacementProperties = cim("CIMStandardGeneralPlacementProperties")
    m.setDefinition(d)
    md = arcpy.metadata.Metadata()
    md.title = "Azulejo Algarve"
    md.summary = "A hand-inked, tile-inspired large-scale basemap of the Algarve, from 1:2M down to street level."
    md.description = ("The Azulejo style for the Algarve: cream land, a cobalt coast inked like a hand-drawn line, soft coastal "
                      "water lines, sandy beaches, golf courses, parks, rivers, roads and place names in Instrument Serif. "
                      "Detail grows with the zoom: web zoom 8 (1:2.3M) shows south Portugal and Andalusia, the Algarve continues to "
                      "street level. Data © OpenStreetMap contributors (ODbL) and Natural Earth.")
    md.tags = "basemap, vector tiles, azulejo, Algarve, Portugal, OpenStreetMap"
    md.credits = "© OpenStreetMap contributors (ODbL); Natural Earth; cartography: Marek Hoffmann; font: Instrument Serif (OFL)"
    m.metadata = md
    return m


def previews(aprx, m):
    lyt = aprx.createLayout(12, 7.5, "INCH", "Preview")
    mf = lyt.createMapFrame(arcpy.Extent(0, 0, 12, 7.5), m, "Map")
    views = {   # centre (lon, lat) and scale
        "2m": ((-7.6, 37.4), 2_000_000), "250k": ((-8.2, 37.12), 250_000),
        "50k": ((-7.93, 37.03), 50_000), "10k": ((-8.672, 37.10), 10_000),
    }
    for name, ((lon, lat), sc) in views.items():
        p = arcpy.PointGeometry(arcpy.Point(lon, lat), arcpy.SpatialReference(4326)).projectAs(WEB_MERCATOR).firstPoint
        mf.camera.X, mf.camera.Y, mf.camera.scale = p.X, p.Y, sc
        png = OUT / f"preview_algarve_{name}.png"
        lyt.exportToPNG(str(png), resolution=96)
        print(f"  {png.name}  1:{mf.camera.scale:,.0f}")
    aprx.save()


if __name__ == "__main__":
    print("geodatabase"); build_gdb()
    shutil.copy(bp.BLANK, APRX)
    aprx = arcpy.mp.ArcGISProject(str(APRX))
    for mm in aprx.listMaps(): aprx.deleteItem(mm)
    print("map"); m = build_map(aprx); aprx.save()
    print("previews"); previews(aprx, m)
    if "--vtpk" in sys.argv:
        # web zoom 8 (1:2.3M) … 17 (1:4.5k); detail beyond comes from overzooming the vector tiles
        arcpy.management.CreateVectorTilePackage(m, str(VTPK), "ONLINE", None, "INDEXED", 2_311_162.217155, 4_513.988705,
                                                 summary="Azulejo Algarve: hand-inked large-scale basemap of the Algarve (OpenStreetMap)",
                                                 tags="basemap, vector tiles, azulejo, Algarve, OpenStreetMap")
        print(f"  {VTPK.name}: {VTPK.stat().st_size / 1e6:.1f} MB")
