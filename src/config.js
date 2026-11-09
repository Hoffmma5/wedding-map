// Everything that describes *this* wedding (place, sides, palette) lives here.
export const VENUE = { place: "Algarve, Portugal", lon: -8.45, lat: 37.12 };

export const SIDES = {
  A: { label: "Marek's people", color: "#1e4bb8" },
  B: { label: "Paulo's people", color: "#c2541f" },
};

export const PALETTE = {
  paper: "#fbf7f0", cream: "#f4eee3", terra: "#c2541f", cobalt: "#1e4bb8",
  olive: "#7f8f5f", sage: "#c9d2ad", portugal: "#e3a57c", ink: "#4a3b2f", sea: "#dfe8f2", orange: "#e8892b",
  background: "#efe7da",
};

// Runtime data (served from public/data). Swap RSVPS_URL for a hosted feature layer later.
const base = import.meta.env.BASE_URL;
export const DATA = {
  rsvps: `${base}data/rsvps.csv`,
  world: `${base}data/world.json`,
  contours: `${base}data/contours.json`,
  relief: proj => `${base}data/relief_${proj}.png`,
  reliefMeta: proj => `${base}data/relief_${proj}.json`,
  currents: `${base}data/currents.json`,
};
