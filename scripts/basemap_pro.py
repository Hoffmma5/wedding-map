"""Build the "Azulejo" Web Mercator basemap in ArcGIS Pro: file geodatabase, Pro project, preview PNGs, vector tile package.

Run with ArcGIS Pro's Python (after scripts/basemap_data.py):
    "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" scripts\\basemap_pro.py [--vtpk]

Outputs in basemap/: Azulejo.gdb, Azulejo.aprx (map "Azulejo basemap"), preview_*.png, Azulejo.vtpk (with --vtpk).
The symbols mirror the web map (src/layers.js): pixel widths there are converted to points here (1 px = 0.75 pt).
"""
import shutil
import sys
from pathlib import Path

import arcpy

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "basemap"
DATA = OUT / "data"
GDB = OUT / "Azulejo.gdb"
APRX = OUT / "Azulejo.aprx"
VTPK = OUT / "Azulejo.vtpk"
BLANK = Path(r"C:\Program Files\ArcGIS\Pro\Resources\ArcToolBox\Services\routingservices\data\Blank.aprx")
WEB_MERCATOR = arcpy.SpatialReference(3857)
arcpy.env.overwriteOutput = True

# ---- palette (the web map's azulejo style) -------------------------------------------------------------------------
COBALT, CREAM, SEA = (30, 75, 184), (251, 247, 240), (223, 232, 242)
INK_ALPHA = 82          # % opacity (the web map's 210/255)
BORDER_ALPHA = 50
# switch between the calm small-scale set and the detailed set (Web Mercator zoom 3 | 4), water-line steps (zoom 5 | 6)
SMALL = 50_000_000
CLOSE = 12_000_000


def cim(name):
    return arcpy.cim.CreateCIMObjectFromClassName(name, "V3")


def color(rgb, alpha=100):
    c = cim("CIMRGBColor"); c.values = [*rgb, alpha]; return c


def stroke(px, rgb, alpha=100):
    s = cim("CIMSolidStroke"); s.enable = True; s.width = px * 0.75; s.color = color(rgb, alpha)
    s.capStyle = "Round"; s.joinStyle = "Round"; s.miterLimit = 4
    return s


def fill(rgb, alpha=100):
    f = cim("CIMSolidFill"); f.enable = True; f.color = color(rgb, alpha); return f


def symbol(kind, layers):
    s = cim("CIMPolygonSymbol" if kind == "polygon" else "CIMLineSymbol"); s.symbolLayers = layers; return s


def water_lines(rings):
    """the coastal water lines: per ring a sea-coloured stroke over a slightly wider faint cobalt one"""
    layers = []
    for k, d in enumerate(rings):
        layers += [stroke(2 * d - 0.8, SEA), stroke(2 * d + 0.8, COBALT, round(16 * (1 - k / 4)))]
    return symbol("polygon", layers)


def style(lyr, sym, name, min_scale=0, max_scale=0):
    d = lyr.getDefinition("V3")
    ref = cim("CIMSymbolReference"); ref.symbol = sym
    r = cim("CIMSimpleRenderer"); r.symbol = ref
    d.renderer = r; d.name = name; d.minScale = min_scale; d.maxScale = max_scale
    lyr.setDefinition(d)
    return lyr


def build_gdb():
    if GDB.exists(): shutil.rmtree(GDB)
    arcpy.management.CreateFileGDB(str(OUT), GDB.name)
    for path in sorted(DATA.glob("*.geojson")):
        geom = "POLYLINE" if path.stem in ("lo_borders", "graticule") else "POLYGON"
        tmp = str(GDB / f"{path.stem}_wgs84")
        arcpy.conversion.JSONToFeatures(str(path), tmp, geom)
        arcpy.management.Project(tmp, str(GDB / path.stem), WEB_MERCATOR)
        arcpy.management.Delete(tmp)
        print(f"  {path.stem:<12} {arcpy.management.GetCount(str(GDB / path.stem))[0]:>6} features")


def build_project():
    shutil.copy(BLANK, APRX)
    aprx = arcpy.mp.ArcGISProject(str(APRX))
    for m in aprx.listMaps(): aprx.deleteItem(m)
    m = aprx.createMap("Azulejo basemap", "MAP")
    for lyr in m.listLayers():   # createMap adds the user's default basemap: not part of this one
        m.removeLayer(lyr)
    m.spatialReference = WEB_MERCATOR
    add = lambda fc: m.addDataFromPath(str(GDB / fc))
    # top → bottom (scale range: min = most zoomed out, max = most zoomed in; 0 = no limit)
    layers = [
        style(add("lo_borders"), symbol("line", [stroke(0.5, COBALT, BORDER_ALPHA)]), "Borders (small scale)", 0, SMALL),
        style(add("lo_land"), symbol("polygon", [fill(CREAM)]), "Land (small scale)", 0, SMALL),
        style(add("countries"), symbol("polygon", [stroke(0.5, COBALT, BORDER_ALPHA), fill(CREAM)]), "Countries", SMALL, 0),
        style(add("lo_wedges"), symbol("polygon", [fill(COBALT, INK_ALPHA)]), "Ink wedges (small scale)", 0, SMALL),
        style(add("lo_ink"), symbol("polygon", [stroke(1.8, COBALT, INK_ALPHA)]), "Coast ink (small scale)", 0, SMALL),
        style(add("ink_wedges"), symbol("polygon", [fill(COBALT, INK_ALPHA)]), "Ink wedges", SMALL, 0),
        style(add("coast_ink"), symbol("polygon", [stroke(1.8, COBALT, INK_ALPHA)]), "Coast ink", SMALL, 0),
        style(add("lo_ink"), water_lines([3]), "Water lines (1 ring)", 0, SMALL),
        style(add("water_lines"), water_lines([3, 7.5]), "Water lines (2 rings)", SMALL, CLOSE),
        style(add("water_lines"), water_lines([3, 7.5, 12]), "Water lines (3 rings)", CLOSE, 0),
        style(add("graticule"), symbol("line", [stroke(0.6, COBALT, 10)]), "Graticule"),
        style(add("ocean"), symbol("polygon", [fill(SEA)]), "Ocean"),
    ]
    for above, below in zip(layers, layers[1:]):   # enforce the stacking order
        m.moveLayer(above, below, "AFTER")
    md = arcpy.metadata.Metadata()   # required by Create Vector Tile Package; ArcGIS Online shows it on the item page
    md.title = "Azulejo"
    md.summary = "A hand-inked, tile-inspired world basemap: cream land, cobalt ink coasts, soft coastal water lines."
    md.description = ("Cartography inspired by Portuguese azulejo tiles. The coast is inked from a slightly coarser, smoothed "
                      "copy of the land, so it wanders like a hand-drawn line; coastal water lines step from one to three rings "
                      "as you zoom in; small scales use a calmer generalization (closed fjords, no specks of islands). "
                      "Data: Natural Earth 1:50m (public domain).")
    md.tags = "basemap, vector tiles, azulejo, cartography, Natural Earth"
    md.credits = "Natural Earth; cartography: Marek Hoffmann"
    m.metadata = md
    aprx.save()
    return aprx, m


def previews(aprx, m):
    lyt = aprx.createLayout(12, 7.5, "INCH", "Preview")
    mf = lyt.createMapFrame(arcpy.Extent(0, 0, 12, 7.5), m, "Map")
    views = {
        "world": arcpy.Extent(-20_037_508, -12_000_000, 20_037_508, 17_000_000, spatial_reference=WEB_MERCATOR),
        "europe": arcpy.Extent(-2_500_000, 3_700_000, 4_200_000, 8_000_000, spatial_reference=WEB_MERCATOR),
        "uk": arcpy.Extent(-1_200_000, 6_300_000, 400_000, 7_400_000, spatial_reference=WEB_MERCATOR),
    }
    for name, ext in views.items():
        mf.camera.setExtent(ext)
        png = OUT / f"preview_{name}.png"
        lyt.exportToPNG(str(png), resolution=96)
        print(f"  preview_{name}.png  scale 1:{mf.camera.scale:,.0f}")
    aprx.save()


def vector_tiles(m):
    # ArcGIS Online / Bing / Google tiling scheme, zoom 0 … 9 (1:1.15M); the data is Natural Earth 1:50m
    arcpy.management.CreateVectorTilePackage(m, str(VTPK), "ONLINE", None, "INDEXED", 295_828_763.795777, 1_155_581.108577,
                                             summary="Azulejo: a hand-inked, tile-inspired world basemap (Natural Earth 1:50m)",
                                             tags="basemap, vector tiles, azulejo, Natural Earth")
    print(f"  {VTPK.name}: {VTPK.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    print("geodatabase"); build_gdb()
    print("project"); aprx, m = build_project()
    print("previews"); previews(aprx, m)
    if "--vtpk" in sys.argv:
        print("vector tile package"); vector_tiles(m)
