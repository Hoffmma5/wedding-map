"""Build the complete "Azulejo" basemap: the world atlas up to web zoom 7, the Algarve from zoom 8 to street level,
in one Pro map and one vector tile package.

Run with ArcGIS Pro's Python after the atlas and Algarve data are built (scripts/basemap_data.py, atlas_data.py,
algarve_pbf.py, algarve_data.py; Azulejo.gdb from scripts/basemap_pro.py):
    "C:\\Program Files\\ArcGIS\\Pro\\bin\\Python\\envs\\arcgispro-py3\\python.exe" scripts\\complete_pro.py [--vtpk]

Outputs basemap/Azulejo_Complete.aprx, preview_complete_*.png and with --vtpk basemap/Azulejo_Complete.vtpk.
"""
import shutil
import sys
from pathlib import Path

import arcpy

import basemap_pro as bp
bp.FONT = "Instrument Serif"
import algarve_pro as ap

OUT = Path(__file__).resolve().parents[1] / "basemap"
APRX = OUT / "Azulejo_Complete.aprx"
VTPK = OUT / "Azulejo_Complete.vtpk"
SWITCH = 8   # web zoom from which the Algarve data takes over from the world atlas (1:2.3M)


def build():
    shutil.copy(bp.BLANK, APRX)
    aprx = arcpy.mp.ArcGISProject(str(APRX))
    for m in aprx.listMaps(): aprx.deleteItem(m)
    m = bp.build_map(aprx, "Azulejo", atlas=True)          # the world atlas (Natural Earth)…
    cut = bp.zoom_scale(SWITCH)
    for lyr in m.listLayers():                              # …switched off from zoom 8
        d = lyr.getDefinition("V3")
        d.maxScale = max(d.maxScale or 0, cut)
        lyr.setDefinition(d)
    ap.add_layers(m)                                        # the Algarve (OpenStreetMap) from zoom 8
    md = arcpy.metadata.Metadata()
    md.title = "Azulejo"
    md.summary = "A hand-inked, tile-inspired basemap: the whole world to 1:4.6M, the Algarve down to street level."
    md.description = ("Cartography inspired by Portuguese azulejo tiles: cream land, a cobalt coast inked like a hand-drawn line, "
                      "soft coastal water lines, inked rivers and lakes, and labels in Instrument Serif. The world (Natural Earth) "
                      "is shown to web zoom 7; from zoom 8 (1:2.3M) the Algarve and south Alentejo continue with OpenStreetMap "
                      "detail to street level: roads, beaches, golf courses, parks, reservoirs and place names. "
                      "Data © OpenStreetMap contributors (ODbL) and Natural Earth.")
    md.tags = "basemap, vector tiles, azulejo, Algarve, Portugal, Natural Earth, OpenStreetMap"
    md.credits = "© OpenStreetMap contributors (ODbL); Natural Earth; cartography: Marek Hoffmann; font: Instrument Serif (OFL)"
    m.metadata = md
    aprx.save()
    return aprx, m


VIEWS = [   # name, (lon, lat), scale
    ("1_world_z2", (10, 30), 120_000_000), ("2_europe_z5", (0, 44), 18_000_000), ("3_before_switch_z7", (-8.0, 37.5), 3_500_000),
    ("4_after_switch_z8", (-8.0, 37.5), 2_200_000), ("5_algarve_250k", (-8.2, 37.12), 250_000),
    ("6_odelouca_50k", (-8.47, 37.30), 50_000), ("7_lagos_10k", (-8.672, 37.10), 10_000),
]


def previews(aprx, m):
    lyt = aprx.createLayout(12, 7.5, "INCH", "Preview")
    mf = lyt.createMapFrame(arcpy.Extent(0, 0, 12, 7.5), m, "Map")
    for name, (lon, lat), sc in VIEWS:
        p = arcpy.PointGeometry(arcpy.Point(lon, lat), arcpy.SpatialReference(4326)).projectAs(bp.WEB_MERCATOR).firstPoint
        mf.camera.X, mf.camera.Y, mf.camera.scale = p.X, p.Y, sc
        png = OUT / f"preview_complete_{name}.png"
        lyt.exportToPNG(str(png), resolution=96)
        print(f"  {png.name}  1:{mf.camera.scale:,.0f}")
    aprx.save()


if __name__ == "__main__":
    print("map"); aprx, m = build()
    print("previews"); previews(aprx, m)
    if "--vtpk" in sys.argv:
        # web zoom 1 (1:296M) … 17 (1:4.5k)
        arcpy.management.CreateVectorTilePackage(m, str(VTPK), "ONLINE", None, "INDEXED", 295_828_763.795777, 4_513.988705,
                                                 summary="Azulejo: hand-inked world basemap with the Algarve to street level",
                                                 tags="basemap, vector tiles, azulejo, Algarve, Natural Earth, OpenStreetMap")
        print(f"  {VTPK.name}: {VTPK.stat().st_size / 1e6:.1f} MB")
