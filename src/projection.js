/* PROJECTION: azimuthal, centred on the venue, so the whole world radiates out from the wedding.
   - laea: Lambert azimuthal equal-area. True areas and true directions from the Algarve.
   - aeqd: Azimuthal equidistant. True directions AND true distances from the Algarve: every straight line from
           the venue is the guest's shortest (great-circle) route, drawn at true length.
   The data is projected here (spherical formulas) and handed to the SDK already in the map's coordinate system;
   the SR is a custom WKT, so the SDK (and projectOperator) know exactly what it is. */
import SpatialReference from "@arcgis/core/geometry/SpatialReference.js";
import Point from "@arcgis/core/geometry/Point.js";
import { VENUE } from "./config.js";
import { VARIANT } from "./variants.js";

export const RE = 6371007.2;
const rad = d => d * Math.PI / 180, deg = r => r * 180 / Math.PI;
const L0 = rad(VENUE.lon), P0 = rad(VENUE.lat), sP0 = Math.sin(P0), cP0 = Math.cos(P0);

const PROJ = {
  laea: { name: "Lambert_Azimuthal_Equal_Area", crop: 166,
    k: c => Math.sqrt(2 / (1 + Math.cos(c))),                       // radial scale as a function of angular distance
    rho: c => 2 * RE * Math.sin(c / 2), c: rho => 2 * Math.asin(Math.min(1, rho / (2 * RE))) },
  aeqd: { name: "Azimuthal_Equidistant", crop: 166,   // all of Australia (Darwin 136°, Sydney 163°)
    k: c => (c < 1e-9 ? 1 : c / Math.sin(c)),
    rho: c => RE * c, c: rho => rho / RE },
};
export const PROJECTION = VARIANT.proj;
const P = PROJ[PROJECTION];

export const SR = new SpatialReference({
  wkt: `PROJCS["Wedding_Algarve_${PROJECTION.toUpperCase()}",GEOGCS["GCS_Sphere_Authalic",DATUM["D_Sphere_Authalic",SPHEROID["Sphere_Authalic",${RE},0.0]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],PROJECTION["${P.name}"],PARAMETER["False_Easting",0.0],PARAMETER["False_Northing",0.0],PARAMETER["Central_Meridian",${VENUE.lon}],PARAMETER["Latitude_Of_Origin",${VENUE.lat}],UNIT["Meter",1.0]]`,
});

/** lon/lat (degrees) → map x/y (metres) */
export function project(lon, lat) {
  const l = rad(lon) - L0, p = rad(lat), cp = Math.cos(p), sp = Math.sin(p), cl = Math.cos(l);
  const c = Math.acos(Math.max(-1, Math.min(1, sP0 * sp + cP0 * cp * cl)));
  const k = RE * P.k(c);
  return [k * cp * Math.sin(l), k * (cP0 * sp - sP0 * cp * cl)];
}
export const laea = project;   // old name, kept for readability in older snippets

/** map x/y → [lon, lat] */
export function unproject(x, y) {
  const rho = Math.hypot(x, y);
  if (rho < 1e-6) return [VENUE.lon, VENUE.lat];
  const c = P.c(rho), sc = Math.sin(c), cc = Math.cos(c);
  const lat = Math.asin(cc * sP0 + y * sc * cP0 / rho);
  const lon = L0 + Math.atan2(x * sc, rho * cP0 * cc - y * sP0 * sc);
  return [((deg(lon) + 540) % 360) - 180, deg(lat)];
}

/** great-circle distance to the venue, km */
export function kmTo(lon, lat) {
  const dp = rad(VENUE.lat - lat), dl = rad(VENUE.lon - lon);
  const h = Math.sin(dp / 2) ** 2 + Math.cos(rad(lat)) * cP0 * Math.sin(dl / 2) ** 2;
  return 2 * RE * Math.asin(Math.sqrt(h)) / 1000;
}

/** lon/lat → Point in the map's spatial reference */
export const geo = (lon, lat) => { const [x, y] = project(lon, lat); return new Point({ x, y, spatialReference: SR }); };

export const CROP_DEG = P.crop;                       // the plate shows the world up to this angular distance
export const PLATE_R = P.rho(rad(CROP_DEG));          // metres
