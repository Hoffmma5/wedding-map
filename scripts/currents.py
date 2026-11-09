"""Ocean surface currents for the flow layer.

Source: NOAA AOML "Near Real Time Geostrophic Currents" (ERDDAP dataset miamicurrents, 0.2°), fetched at 0.4°:
  curl -L -o data-raw/currents.nc "https://coastwatch.pfeg.noaa.gov/erddap/griddap/miamicurrents.nc?u_current%5B(last)%5D%5B(-64.7):2:(64.7)%5D%5B(-179.9):2:(179.9)%5D,v_current%5B(last)%5D%5B(-64.7):2:(64.7)%5D%5B(-179.9):2:(179.9)%5D"

Output: public/data/currents.json  {meta…, u, v} with u/v as base64 Int16 (cm/s), rows south→north, 0.8° grid.
"""
import base64, json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.io import netcdf_file
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).resolve().parents[1]
with netcdf_file(ROOT / "data-raw/currents.nc", "r", mmap=False) as nc:
    lat = nc.variables["latitude"][:].astype(float)
    lon = nc.variables["longitude"][:].astype(float)
    t = float(nc.variables["time"][0])
    u = nc.variables["u_current"][0].astype(np.float32)
    v = nc.variables["v_current"][0].astype(np.float32)
if lat[0] > lat[-1]:
    lat, u, v = lat[::-1], u[::-1], v[::-1]
for a in (u, v):
    a[~np.isfinite(a) | (np.abs(a) > 10)] = np.nan

def block(a, k=2):                       # nan-aware 2×2 mean → 0.8°
    h, w = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    b = a[:h, :w].reshape(h // k, k, w // k, k)
    with np.errstate(invalid="ignore"):
        return np.nanmean(b, axis=(1, 3))

def smooth(a, sigma=1.4):              # nan-aware Gaussian: removes altimetry noise, keeps the coastline mask
    ok = np.isfinite(a); w = gaussian_filter(ok.astype(np.float32), sigma)
    with np.errstate(invalid="ignore", divide="ignore"):
        s = gaussian_filter(np.where(ok, a, 0), sigma) / w
    s[~ok] = np.nan
    return s

u, v = block(smooth(u)), block(smooth(v))
lat = lat[: (len(lat) // 2) * 2].reshape(-1, 2).mean(1)
lon = lon[: (len(lon) // 2) * 2].reshape(-1, 2).mean(1)
enc = lambda a: base64.b64encode(np.where(np.isfinite(a), np.round(a * 100), -32768).astype("<i2").tobytes()).decode()
out = {
    "source": "NOAA AOML Near Real Time Geostrophic Currents (miamicurrents)",
    "date": datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d"),
    "lon0": float(lon[0]), "lat0": float(lat[0]), "dlon": float(lon[1] - lon[0]), "dlat": float(lat[1] - lat[0]),
    "w": int(u.shape[1]), "h": int(u.shape[0]), "unit": "cm/s", "nodata": -32768,
    "u": enc(u), "v": enc(v),
}
p = ROOT / "public/data/currents.json"
p.write_text(json.dumps(out, separators=(",", ":")))
print(p.name, p.stat().st_size // 1024, "KB", out["date"], out["w"], "x", out["h"])
