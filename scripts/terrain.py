"""Elevation products for the map, from ETOPO1 (NOAA, public domain) at 10 arc-minutes.

Download (≈4.7 MB) into data-raw/ first:
  curl -L -o data-raw/etopo_10min.nc "https://coastwatch.pfeg.noaa.gov/erddap/griddap/etopo180.nc?altitude%5B(-90.0):10:(90.0)%5D%5B(-180.0):10:(180.0)%5D"

Outputs (public/data):
  contours.json  sea (bathymetry) and land (elevation) contour lines, lon/lat, simplified
  relief_<proj>.png/.json  multi-directional hillshade (shadows only) as cobalt ink with alpha, already
                           projected into the plate of each projection (laea, aeqd); see PLATES below
"""
import json
from pathlib import Path

import numpy as np
from contourpy import contour_generator
from PIL import Image
from scipy.io import netcdf_file
from scipy.ndimage import gaussian_filter
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data-raw/etopo_10min.nc"
OUT = ROOT / "public/data"

with netcdf_file(RAW, "r", mmap=False) as nc:
    lat = nc.variables["latitude"][:].astype(float)
    lon = nc.variables["longitude"][:].astype(float)
    z = nc.variables["altitude"][:].astype(np.float32)
if lat[0] > lat[-1]:
    lat, z = lat[::-1], z[::-1]

# ---- contours ---------------------------------------------------------------
SEA = [-200, -1000, -2000, -3000, -4000, -5000]
LAND = [300, 1000, 2000, 3000, 4500]
zs = gaussian_filter(z, 1.2)            # soft, hand-drawn looking lines
gen = contour_generator(lon, lat, zs, line_type="Separate")

def lines(level, tol, min_len):
    out = []
    for seg in gen.lines(level):
        if len(seg) < 4:
            continue
        ls = LineString(seg)
        if ls.length < min_len:
            continue
        if seg[:, 1].max() < -60:       # no Antarctica
            continue
        s = ls.simplify(tol, preserve_topology=False)
        c = [round(v, 2) for xy in s.coords for v in xy]
        if len(c) >= 6:
            out.append(c)
    return out

contours = {
    "sea": [{"z": lv, "l": lines(lv, 0.06, 1.5)} for lv in SEA],
    "land": [{"z": lv, "l": lines(lv, 0.05, 1.0)} for lv in LAND],
}
(OUT / "contours.json").write_text(json.dumps(contours, separators=(",", ":")))

# ---- hillshade (land only) ----------------------------------------------------
# multi-directional hillshade on the lon/lat grid with true cell sizes, stored as shadow strength (0 = lit, 255 = deep shadow)
keep = (lat >= -60) & (lat <= 84)
zz = gaussian_filter(np.clip(z, 0, None), 0.6)[keep][::-1].astype(np.float64)     # north → south
la = np.radians(lat[keep][::-1])[:, None]
dy = np.radians(lat[1] - lat[0]) * 6371000.0
dx = np.radians(lon[1] - lon[0]) * 6371000.0 * np.maximum(np.cos(la), 0.05)
EXAG = 12.0                                              # vertical exaggeration: cells are ~18 km wide
gy, gx = np.gradient(zz * EXAG)
sx, sy = gx / dx, -gy / dy                               # d z / d east, d z / d north
slope = np.arctan(np.hypot(sx, sy)); aspect = np.arctan2(-sx, -sy)
alt = np.radians(45)
shade = np.zeros_like(zz)
for az, wgt in [(315, 0.5), (270, 0.2), (360, 0.2), (225, 0.1)]:
    a = np.radians(az)
    shade += wgt * (np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(a - aspect))
flat = np.sin(alt)
shadow = np.clip((flat - shade) / flat, 0, 1)            # only the shadowed side
shadow = np.clip(shadow / np.percentile(shadow[shadow > 0.01], 97), 0, 1) ** 0.7   # normalised contrast
shadow[zz <= 0] = 0
# ---- relief images, pre-projected into each plate (must match src/projection.js) ---------------------------
from scipy.ndimage import map_coordinates
RE, VLON, VLAT = 6371007.2, -8.45, 37.12
PLATES = {"laea": 155.4, "aeqd": 122}        # crop (degrees from the venue) per projection, as in projection.js
SIZE = 2800
L0, P0 = np.radians(VLON), np.radians(VLAT)
lat_top = float(lat[keep].max())
for proj, crop in PLATES.items():
    c_max = np.radians(crop)
    R = 2 * RE * np.sin(c_max / 2) if proj == "laea" else RE * c_max
    step = 2 * R / SIZE
    xs = -R + (np.arange(SIZE) + 0.5) * step
    X, Y = np.meshgrid(xs, -xs)                          # rows north → south
    rho = np.hypot(X, Y)
    c = 2 * np.arcsin(np.clip(rho / (2 * RE), 0, 1)) if proj == "laea" else rho / RE
    sc, cc = np.sin(c), np.cos(c)
    with np.errstate(invalid="ignore", divide="ignore"):
        la_ = np.arcsin(np.clip(cc * np.sin(P0) + np.where(rho > 0, Y * sc * np.cos(P0) / rho, 0), -1, 1))
    lo_ = L0 + np.arctan2(X * sc, rho * np.cos(P0) * cc - Y * np.sin(P0) * sc)
    lon_d = (np.degrees(lo_) + 540) % 360 - 180; lat_d = np.degrees(la_)
    row = (lat_top - lat_d) / (lat[1] - lat[0]); col = (lon_d - lon[0]) / (lon[1] - lon[0])
    a = map_coordinates(shadow, [row, col], order=1, mode="constant", cval=0)
    a[rho > R] = 0
    alpha = np.round(np.clip(a, 0, 1) * 255).astype(np.uint8)
    rgba = np.zeros((SIZE, SIZE, 4), np.uint8); rgba[..., 0], rgba[..., 1], rgba[..., 2] = 30, 75, 184; rgba[..., 3] = alpha
    Image.fromarray(rgba, "RGBA").save(OUT / f"relief_{proj}.png", optimize=True)
    (OUT / f"relief_{proj}.json").write_text(json.dumps({"radius": R, "size": SIZE, "crop": crop}))

for f in ["contours.json", "relief_laea.png", "relief_aeqd.png"]:
    print(f, (OUT / f).stat().st_size // 1024, "KB")
print({k: [len(c["l"]) for c in v] for k, v in contours.items()})
