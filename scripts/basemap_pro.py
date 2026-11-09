"""Build the "Azulejo" Web Mercator basemaps in ArcGIS Pro: file geodatabase, Pro project, preview PNGs, vector tile packages.

Run with ArcGIS Pro's Python (after scripts/basemap_data.py and scripts/atlas_data.py):
    "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" scripts\\basemap_pro.py [--vtpk] [--atlas-only]

Outputs in basemap/: Azulejo.gdb, Azulejo.aprx (maps "Azulejo basemap" and "Azulejo atlas"), preview_*.png,
and with --vtpk Azulejo.vtpk + Azulejo_Atlas.vtpk (--atlas-only: previews and package of the atlas only).
The symbols mirror the web map (src/layers.js): pixel widths there are converted to points here (1 px = 0.75 pt).
Atlas labels: Avenir Next LT Pro by default, or --font="Instrument Serif" once that font is installed for all users.
"""
import copy
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
ATLAS_VTPK = OUT / "Azulejo_Atlas.vtpk"
BLANK = Path(r"C:\Program Files\ArcGIS\Pro\Resources\ArcToolBox\Services\routingservices\data\Blank.aprx")
WEB_MERCATOR = arcpy.SpatialReference(3857)
arcpy.env.overwriteOutput = True

# ---- palette (the web map's azulejo style) -------------------------------------------------------------------------
COBALT, CREAM, SEA = (30, 75, 184), (251, 247, 240), (223, 232, 242)
INK = (22, 40, 96)      # blue-black ink for city names
INK_ALPHA = 82          # % opacity (the web map's 210/255)
BORDER_ALPHA = 50
# Label font. Instrument Serif (SIL OFL) is the intended one, but Pro can only embed a font Windows will load: on machines
# with the "block untrusted fonts" policy that means installed for all users (C:\Windows\Fonts). Until then the default
# is Avenir Next LT Pro, which ships with ArcGIS Pro for use in maps and vector tiles. Override: --font="Instrument Serif"
FONT = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--font=")), "Avenir Next LT Pro")
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


def dashed(stroke_layer, template=(3.0, 2.0)):
    """a dash pattern (in points) on a stroke: the atlas draws country borders dashed"""
    e = cim("CIMGeometricEffectDashes"); e.dashTemplate = list(template); e.lineDashEnding = "NoConstraint"
    stroke_layer.effects = [e]
    return stroke_layer


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


POINTS = {"atlas_cities", "atlas_country_labels", "atlas_marine_labels", "atlas_lake_labels"}
LINES = {"lo_borders", "graticule", "atlas_rivers"}


def build_gdb():
    if GDB.exists(): shutil.rmtree(GDB)
    arcpy.management.CreateFileGDB(str(OUT), GDB.name)
    for path in sorted(DATA.glob("*.geojson")):
        geom = "POINT" if path.stem in POINTS else "POLYLINE" if path.stem in LINES else "POLYGON"
        tmp = str(GDB / f"{path.stem}_wgs84")
        arcpy.conversion.JSONToFeatures(str(path), tmp, geom)
        arcpy.management.Project(tmp, str(GDB / path.stem), WEB_MERCATOR)
        arcpy.management.Delete(tmp)
        print(f"  {path.stem:<22} {arcpy.management.GetCount(str(GDB / path.stem))[0]:>6} features")


# ---- atlas: zoom levels, points and labels ----------------------------------------------------------------------
def zoom_scale(z):
    """web-map scale at zoom z, a hair larger so the layer is already on at that zoom level"""
    return 591_657_527.591555 / 2 ** z * 1.01


def points(lyr, size=0.0, fill_rgb=CREAM, outline_rgb=COBALT, outline=0.0, visible=True):
    """city dots (cream with a cobalt ring), or an invisible anchor for a label-only layer"""
    sym = lyr.symbology
    sym.renderer.symbol.applySymbolFromGallery("Circle 1")
    s = sym.renderer.symbol
    s.size = size if visible else 0.1
    s.color = {"RGB": [*fill_rgb, 100 if visible else 0]}
    s.outlineColor = {"RGB": [*outline_rgb, 100 if visible else 0]}
    s.outlineWidth = outline if visible else 0
    lyr.symbology = sym
    return lyr


def text_symbol(ts, size, rgb, alpha=100, italic=False, halo_rgb=CREAM, spacing=0.0):
    ts.fontFamilyName = FONT
    ts.fontStyleName = "Italic" if italic else "Regular"
    ts.height = size
    ts.letterSpacing = spacing
    ts.symbol = symbol("polygon", [fill(rgb, alpha)])
    ts.haloSize = 1.1
    ts.haloSymbol = symbol("polygon", [fill(halo_rgb, 90)])
    ts.horizontalAlignment = "Center"


def labels(lyr, classes, kind="point", on_top=False):
    """classes: (name, where, size, rgb, alpha, italic, halo, letter spacing, priority) per label class"""
    lyr.showLabels = True
    d = lyr.getDefinition("V3")
    base = d.labelClasses[0]
    out = []
    for name, where, size, rgb, alpha, italic, halo, spacing, priority in classes:
        lc = copy.deepcopy(base)
        lc.name = name; lc.whereClause = where or ""; lc.expression = "$feature.label"; lc.expressionEngine = "Arcade"
        lc.priority = priority; lc.visibility = True
        text_symbol(lc.textSymbol.symbol, size, rgb, alpha, italic, halo, spacing)
        sp = lc.standardLabelPlacementProperties
        if kind == "line":
            sp.featureType = "Line"
            sp.lineLabelPosition.produceCurvedLabels = True
            sp.lineLabelPosition.parallel = True
            sp.lineLabelPosition.above = True     # beside the river, not through it
            sp.lineLabelPosition.onTop = False
            sp.lineLabelPosition.inLine = False
            sp.numLabelsOption = "OneLabelPerName"
        else:
            sp.featureType = "Point"
            sp.pointPlacementMethod = "OnTopPoint" if on_top else "AroundPoint"
        out.append(lc)
    d.labelClasses = out
    lyr.setDefinition(d)
    return lyr


def scale(lyr, name, z_from=None, where=None):
    """layer name, definition query and the zoom level it appears at"""
    if where: lyr.definitionQuery = where
    d = lyr.getDefinition("V3")
    d.name = name
    d.minScale = zoom_scale(z_from) if z_from is not None else 0
    d.maxScale = 0
    lyr.setDefinition(d)
    return lyr


def atlas_layers(add):
    """rivers, lakes, cities and labels; returned as (above the borders, between borders and land), top → bottom"""
    river_classes = [("Rivers (major)", "min_zoom <= 2.5", 1.8, 2), ("Rivers (large)", "min_zoom > 2.5 AND min_zoom <= 3.5", 1.6, 3),
                     ("Rivers (medium)", "min_zoom > 3.5 AND min_zoom <= 4.5", 1.4, 4), ("Rivers (small)", "min_zoom > 4.5 AND min_zoom <= 5.5", 1.15, 5),
                     ("Rivers (minor)", "min_zoom > 5.5", 0.95, 6)]
    # inked like the coast, thinner the smaller the river (the borders are dashed, so the two never get confused)
    rivers = [scale(style(add("atlas_rivers"), symbol("line", [stroke(w, COBALT, 92)]), n), n, z, where=q) for n, q, w, z in river_classes]
    lake_classes = [("Lakes (large)", "min_zoom <= 3", 2), ("Lakes (medium)", "min_zoom > 3 AND min_zoom <= 5", 4), ("Lakes (small)", "min_zoom > 5", 5)]
    lakes = [scale(style(add("atlas_lakes"), symbol("polygon", [stroke(1.0, COBALT, INK_ALPHA), fill(SEA)]), n), n, z, where=q) for n, q, z in lake_classes]

    def water(size, alpha=80, spacing=0.0):
        return (size, COBALT, alpha, True, SEA, spacing)

    above = []
    # seas and oceans: italic water labels, oceans in spaced capitals
    above.append(scale(labels(points(add("atlas_marine_labels"), visible=False),
                              [("Oceans", None, *water(13, 60, 25.0), 1)], on_top=True), "Ocean labels", 1, where="kind = 'ocean'"))
    for n, q, z in [("Sea labels (large)", "kind <> 'ocean' AND min_zoom <= 3", 3),
                    ("Sea labels (medium)", "kind <> 'ocean' AND min_zoom > 3 AND min_zoom <= 5", 5),
                    ("Sea labels (small)", "kind <> 'ocean' AND min_zoom > 5", 6)]:
        above.append(scale(labels(points(add("atlas_marine_labels"), visible=False), [(n, None, *water(9.5), 3)], on_top=True), n, z, where=q))
    above.append(scale(labels(points(add("atlas_lake_labels"), visible=False), [("Lakes", None, *water(8.5), 5)], on_top=True), "Lake labels", 5))
    # countries: spaced capitals in cobalt, bigger for the large ones
    for tag, q, z in [("z2", "min_zoom <= 2.5", 2), ("z3", "min_zoom > 2.5 AND min_zoom <= 3.5", 3),
                      ("z4", "min_zoom > 3.5 AND min_zoom <= 4.5", 4), ("z5", "min_zoom > 4.5", 5)]:
        above.append(scale(labels(points(add("atlas_country_labels"), visible=False), [
            ("Large countries", "rank <= 2", 11.5, COBALT, 75, False, CREAM, 22.0, 2),
            ("Countries", "rank > 2", 9.0, COBALT, 75, False, CREAM, 18.0, 2)], on_top=True), f"Country labels ({tag})", z, where=q))
    # cities: cream dot with a cobalt ring; capitals a little larger
    for z in (3, 4, 5, 6, 7):
        q = f"min_zoom <= {z + 0.5}" if z == 3 else f"min_zoom > {z - 0.5} AND min_zoom <= {z + 0.5}"
        above.append(scale(labels(points(add("atlas_cities"), size=4.5 if z <= 4 else 3.8, outline=0.9), [
            ("Capitals", "capital = 1", 10.0 if z <= 4 else 9.0, INK, 100, False, CREAM, 0.0, 1),
            ("Cities", "capital = 0", 9.0 if z <= 4 else 8.0, INK, 100, False, CREAM, 0.0, 4)]), f"Cities (z{z})", z, where=q))
    # river names along the rivers: italic, curved
    for n, q, z in [("River labels (large)", "label <> '' AND min_label <= 4.5", 4),
                    ("River labels (small)", "label <> '' AND min_label > 4.5 AND min_label <= 6.5", 6)]:
        above.append(scale(labels(style(add("atlas_rivers"), symbol("line", [stroke(0.5, COBALT, 0)]), n),
                                  [(n, None, 8.0, COBALT, 90, True, CREAM, 0.0, 6)], kind="line"), n, z, where=q))   # on land: cream halo
    return above, lakes + rivers


def build_map(aprx, name, atlas=False):
    m = aprx.createMap(name, "MAP")
    for lyr in m.listLayers():   # createMap adds the user's default basemap: not part of this one
        m.removeLayer(lyr)
    m.spatialReference = WEB_MERCATOR
    add = lambda fc: m.addDataFromPath(str(GDB / fc))
    above, below = atlas_layers(add) if atlas else ([], [])
    # top → bottom (scale range: min = most zoomed out, max = most zoomed in; 0 = no limit)
    border = lambda: dashed(stroke(0.6, COBALT, 60)) if atlas else stroke(0.5, COBALT, BORDER_ALPHA)
    layers = above + [
        style(add("lo_borders"), symbol("line", [border()]), "Borders (small scale)", 0, SMALL),
    ] + below + [
        style(add("lo_land"), symbol("polygon", [fill(CREAM)]), "Land (small scale)", 0, SMALL),
        style(add("countries"), symbol("polygon", [border(), fill(CREAM)]), "Countries", SMALL, 0),
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
    for upper, lower in zip(layers, layers[1:]):   # enforce the stacking order
        m.moveLayer(upper, lower, "AFTER")
    if atlas:   # vector tiles are labelled with the Standard label engine
        d = m.getDefinition("V3")
        d.generalPlacementProperties = cim("CIMStandardGeneralPlacementProperties")
        m.setDefinition(d)
    md = arcpy.metadata.Metadata()   # required by Create Vector Tile Package; ArcGIS Online shows it on the item page
    md.title = "Azulejo atlas" if atlas else "Azulejo"
    md.summary = ("A hand-inked, tile-inspired world basemap with rivers, lakes, cities and labels." if atlas else
                  "A hand-inked, tile-inspired world basemap: cream land, cobalt ink coasts, soft coastal water lines.")
    md.description = ("Cartography inspired by Portuguese azulejo tiles. The coast is inked from a slightly coarser, smoothed "
                      "copy of the land, so it wanders like a hand-drawn line; coastal water lines step from one to three rings "
                      "as you zoom in; small scales use a calmer generalization (closed fjords, no specks of islands). "
                      + (f"Rivers and lakes are inked like the coast; cities and labels appear by zoom level, set in {FONT}. "
                         if atlas else "")
                      + "Data: Natural Earth (public domain).")
    md.tags = "basemap, vector tiles, azulejo, cartography, Natural Earth" + (", labels, atlas" if atlas else "")
    md.credits = "Natural Earth; cartography: Marek Hoffmann" + (f"; font: {FONT}" if atlas else "")
    m.metadata = md
    return m


def build_project():
    shutil.copy(BLANK, APRX)
    aprx = arcpy.mp.ArcGISProject(str(APRX))
    for m in aprx.listMaps(): aprx.deleteItem(m)
    maps = {"basemap": build_map(aprx, "Azulejo basemap"), "atlas": build_map(aprx, "Azulejo atlas", atlas=True)}
    aprx.save()
    return aprx, maps


def previews(aprx, maps, which):
    lyt = aprx.createLayout(12, 7.5, "INCH", "Preview")
    views = {
        "world": arcpy.Extent(-20_037_508, -12_000_000, 20_037_508, 17_000_000, spatial_reference=WEB_MERCATOR),
        "europe": arcpy.Extent(-2_500_000, 3_700_000, 4_200_000, 8_000_000, spatial_reference=WEB_MERCATOR),
        "uk": arcpy.Extent(-1_200_000, 6_300_000, 400_000, 7_400_000, spatial_reference=WEB_MERCATOR),
        "iberia": arcpy.Extent(-1_300_000, 4_200_000, 600_000, 5_500_000, spatial_reference=WEB_MERCATOR),
    }
    for key in which:
        mf = lyt.createMapFrame(arcpy.Extent(0, 0, 12, 7.5), maps[key], f"Map {key}")
        for name, ext in views.items():
            mf.camera.setExtent(ext)
            png = OUT / f"preview_{key}_{name}.png"
            lyt.exportToPNG(str(png), resolution=96)
            print(f"  {png.name}  scale 1:{mf.camera.scale:,.0f}")
        lyt.deleteElement(mf)
    aprx.save()


def vector_tiles(m, path, summary, tags):
    # ArcGIS Online / Bing / Google tiling scheme, zoom 1 … 9 (1:1.15M); Natural Earth 1:50m (cities 1:10m)
    arcpy.management.CreateVectorTilePackage(m, str(path), "ONLINE", None, "INDEXED", 295_828_763.795777, 1_155_581.108577,
                                             summary=summary, tags=tags)
    print(f"  {path.name}: {path.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    which = ["atlas"] if "--atlas-only" in sys.argv else ["basemap", "atlas"]
    print("geodatabase"); build_gdb()
    print("project"); aprx, maps = build_project()
    print("previews"); previews(aprx, maps, which)
    if "--vtpk" in sys.argv:
        print("vector tile packages")
        if "basemap" in which:
            vector_tiles(maps["basemap"], VTPK, "Azulejo: a hand-inked, tile-inspired world basemap (Natural Earth)",
                         "basemap, vector tiles, azulejo, Natural Earth")
        vector_tiles(maps["atlas"], ATLAS_VTPK,
                     "Azulejo atlas: hand-inked world basemap with rivers, lakes, cities and labels (Natural Earth)",
                     "basemap, vector tiles, azulejo, labels, Natural Earth")
