import { DATA } from "./config.js";

/** Minimal RFC 4180 CSV parser (quoted fields, embedded commas/quotes/newlines). */
export function parseCsv(text) {
  const rows = []; let row = [], field = "", q = false;
  text = text.replace(/^﻿/, "");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) {
      if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else q = false; }
      else field += c;
    } else if (c === '"') q = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  const [head, ...body] = rows;
  return body.map(r => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""])));
}

const NUMERIC = ["party_size", "lon", "lat"];

/** One row per party: rsvp_id, party_lead, party_size, side, relation, city, country, lon, lat, transport, arrival_day, note */
export async function loadRsvps(url = DATA.rsvps) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`RSVPs: ${res.status} ${url}`);
  return parseCsv(await res.text()).map(r => {
    for (const k of NUMERIC) r[k] = Number(r[k]);
    return r;
  });
}

export async function loadJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.json();
}

/** Natural Earth 1:50m countries (flat lon/lat rings), ocean wave points, graticule. Built by scripts/world.py */
export const loadWorld = (url = DATA.world) => loadJson(url);

/** Aggregate parties to one origin per city & side */
export function toOrigins(rsvps) {
  return Object.values(rsvps.reduce((acc, r) => {
    const k = r.city + "|" + r.side;
    const o = acc[k] ??= { city: r.city, country: r.country, lon: r.lon, lat: r.lat, side: r.side, guests: 0, parties: [], modes: {}, note: "" };
    o.guests += r.party_size; o.parties.push(r);
    o.modes[r.transport] = (o.modes[r.transport] || 0) + r.party_size;
    if (!o.note && r.note) o.note = r.note;
    return acc;
  }, {}));
}
