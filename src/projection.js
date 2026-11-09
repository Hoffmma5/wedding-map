/* PROJECTION: Lambert azimuthal equal-area centred on the venue.
   Every country keeps its true area, and every direction from the Algarve is true,
   so the whole world literally radiates out from the wedding.
   The data is projected here (spherical formulas, authalic sphere) and handed to the SDK already in the map's
   coordinate system. */
import SpatialReference from "@arcgis/core/geometry/SpatialReference.js";
import Point from "@arcgis/core/geometry/Point.js";
import { VENUE } from "./config.js";

export const RE = 6371007.2;
const rad = d => d * Math.PI / 180;

export const SR = new SpatialReference({
  wkt: `PROJCS["Wedding_Algarve_LAEA",GEOGCS["GCS_Sphere_Authalic",DATUM["D_Sphere_Authalic",SPHEROID["Sphere_Authalic",${RE},0.0]],PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],PROJECTION["Lambert_Azimuthal_Equal_Area"],PARAMETER["False_Easting",0.0],PARAMETER["False_Northing",0.0],PARAMETER["Central_Meridian",${VENUE.lon}],PARAMETER["Latitude_Of_Origin",${VENUE.lat}],UNIT["Meter",1.0]]`,
});

const L0 = rad(VENUE.lon), P0 = rad(VENUE.lat);

export function laea(lon, lat) {
  const l = rad(lon) - L0, p = rad(lat);
  const k = Math.sqrt(2 / (1 + Math.sin(P0) * Math.sin(p) + Math.cos(P0) * Math.cos(p) * Math.cos(l)));
  return [RE * k * Math.cos(p) * Math.sin(l), RE * k * (Math.cos(P0) * Math.sin(p) - Math.sin(P0) * Math.cos(p) * Math.cos(l))];
}

/** great-circle distance to the venue, km */
export function kmTo(lon, lat) {
  const dp = rad(VENUE.lat - lat), dl = rad(VENUE.lon - lon);
  const h = Math.sin(dp / 2) ** 2 + Math.cos(rad(lat)) * Math.cos(P0) * Math.sin(dl / 2) ** 2;
  return 2 * RE * Math.asin(Math.sqrt(h)) / 1000;
}

/** lon/lat → Point in the map's spatial reference */
export const geo = (lon, lat) => { const [x, y] = laea(lon, lat); return new Point({ x, y, spatialReference: SR }); };

export const PLATE_R = 12_450_000; // metres; ~150° from the venue
